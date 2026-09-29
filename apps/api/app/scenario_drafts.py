"""Versioned user scenario drafts built only from validated economic templates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from .db.database import Database
from .db.models import ScenarioDraftVersion
from .domain.scenario import ScenarioDefinition
from .models import (
    Scenario,
    ScenarioBoundaryCheck,
    ScenarioDraftRequest,
    ScenarioDraftResponse,
)
from .scenario_catalog import ScenarioCatalog
from .tasking import participant_tasks


@dataclass(frozen=True, slots=True)
class StoredScenarioDraft:
    id: UUID
    series_id: UUID
    user_id: UUID
    version: int
    scenario: Scenario
    definition: ScenarioDefinition
    validation: ScenarioBoundaryCheck
    input_payload: dict
    created_at: datetime

    def response(self) -> ScenarioDraftResponse:
        return ScenarioDraftResponse(
            id=self.id,
            series_id=self.series_id,
            version=self.version,
            scenario=self.scenario,
            validation=self.validation,
            created_at=self.created_at,
        )


class ScenarioDraftRepository(Protocol):
    def next_version(self, user_id: UUID, series_id: UUID) -> int: ...
    def save(self, draft: StoredScenarioDraft) -> StoredScenarioDraft: ...
    def list_for_user(self, user_id: UUID) -> tuple[StoredScenarioDraft, ...]: ...
    def list_all(self) -> tuple[StoredScenarioDraft, ...]: ...
    def delete_for_user(self, user_id: UUID) -> None: ...


class InMemoryScenarioDraftRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, StoredScenarioDraft] = {}

    def next_version(self, user_id: UUID, series_id: UUID) -> int:
        versions = [
            item.version for item in self._items.values()
            if item.user_id == user_id and item.series_id == series_id
        ]
        if not versions and any(item.series_id == series_id for item in self._items.values()):
            raise PermissionError("draft_series_not_owned")
        return max(versions, default=0) + 1

    def save(self, draft: StoredScenarioDraft) -> StoredScenarioDraft:
        self._items[draft.id] = draft
        return draft

    def list_for_user(self, user_id: UUID) -> tuple[StoredScenarioDraft, ...]:
        return tuple(sorted(
            (item for item in self._items.values() if item.user_id == user_id),
            key=lambda item: item.created_at,
            reverse=True,
        ))

    def list_all(self) -> tuple[StoredScenarioDraft, ...]:
        return tuple(self._items.values())

    def delete_for_user(self, user_id: UUID) -> None:
        self._items = {key: item for key, item in self._items.items() if item.user_id != user_id}


class SqlAlchemyScenarioDraftRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def next_version(self, user_id: UUID, series_id: UUID) -> int:
        with self._database.session_factory() as db:
            owners = set(db.scalars(
                select(ScenarioDraftVersion.user_id).where(
                    ScenarioDraftVersion.series_id == str(series_id)
                )
            ).all())
            if owners and str(user_id) not in owners:
                raise PermissionError("draft_series_not_owned")
            maximum = db.scalar(
                select(func.max(ScenarioDraftVersion.version_number)).where(
                    ScenarioDraftVersion.series_id == str(series_id),
                    ScenarioDraftVersion.user_id == str(user_id),
                )
            )
            return int(maximum or 0) + 1

    def save(self, draft: StoredScenarioDraft) -> StoredScenarioDraft:
        with self._database.session_factory.begin() as db:
            db.add(ScenarioDraftVersion(
                id=str(draft.id),
                series_id=str(draft.series_id),
                user_id=str(draft.user_id),
                version_number=draft.version,
                scenario_id=draft.scenario.id,
                input_payload=draft.input_payload,
                definition=draft.definition.model_dump(mode="json"),
                public_projection=draft.scenario.model_dump(mode="json"),
                validation=draft.validation.model_dump(mode="json"),
                created_at=draft.created_at,
            ))
        return draft

    def list_for_user(self, user_id: UUID) -> tuple[StoredScenarioDraft, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                select(ScenarioDraftVersion)
                .where(ScenarioDraftVersion.user_id == str(user_id))
                .order_by(ScenarioDraftVersion.created_at.desc())
            ).all()
            return tuple(self._domain(item) for item in rows)

    def list_all(self) -> tuple[StoredScenarioDraft, ...]:
        with self._database.session_factory() as db:
            return tuple(self._domain(item) for item in db.scalars(select(ScenarioDraftVersion)).all())

    def delete_for_user(self, user_id: UUID) -> None:
        with self._database.session_factory.begin() as db:
            db.execute(delete(ScenarioDraftVersion).where(ScenarioDraftVersion.user_id == str(user_id)))

    @staticmethod
    def _domain(row: ScenarioDraftVersion) -> StoredScenarioDraft:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return StoredScenarioDraft(
            id=UUID(row.id),
            series_id=UUID(row.series_id),
            user_id=UUID(row.user_id),
            version=row.version_number,
            scenario=Scenario.model_validate(row.public_projection),
            definition=ScenarioDefinition.model_validate_json(json.dumps(row.definition)),
            validation=ScenarioBoundaryCheck.model_validate(row.validation),
            input_payload=dict(row.input_payload),
            created_at=created_at,
        )


def simulate_boundaries(definition: ScenarioDefinition) -> ScenarioBoundaryCheck:
    """Recalculate the critical boundary facts after full domain validation."""

    # Revalidation exercises the complete graph, including exact ZOPA bounds,
    # party ranges, offer domains and method/type compatibility.
    checked = ScenarioDefinition.model_validate_json(definition.model_dump_json())
    overlaps = sum(item.status == "overlap" for item in checked.zopa)
    return ScenarioBoundaryCheck(
        checked_issues=len(checked.issues),
        overlapping_issues=overlaps,
        no_overlap_issues=len(checked.issues) - overlaps,
    )


def _scale_primary_issue(payload: dict, factor: float) -> None:
    issue = next((item for item in payload["issues"] if "руб" in item["unit"].casefold()), payload["issues"][0])
    issue_id = issue["id"]
    for party_range in issue["party_ranges"].values():
        for key in ("minimum", "maximum", "reservation", "aspiration"):
            party_range[key] = round(float(party_range[key]) * factor, 2)
    zopa = next(item for item in payload["zopa"] if item["issue_id"] == issue_id)
    if zopa["status"] == "overlap":
        zopa["lower"] = round(float(zopa["lower"]) * factor, 2)
        zopa["upper"] = round(float(zopa["upper"]) * factor, 2)
    for offer in payload["offer_templates"]:
        if issue_id in offer["values"]:
            offer["values"][issue_id] = round(float(offer["values"][issue_id]) * factor, 2)
    for condition in (*payload["success_conditions"], *payload["impasse_conditions"], *payload["walk_away_conditions"]):
        for predicate in condition["predicates"]:
            if predicate.get("issue_id") == issue_id and isinstance(predicate.get("value"), (int, float)):
                predicate["value"] = round(float(predicate["value"]) * factor, 2)


def compile_draft(
    catalog: ScenarioCatalog,
    request: ScenarioDraftRequest,
    series_id: UUID,
    version: int,
) -> tuple[Scenario, ScenarioDefinition, ScenarioBoundaryCheck]:
    template = catalog.get_definition(request.template_id)
    template_public = catalog.get(request.template_id)
    if template is None or template_public is None or template_public.source == "custom":
        raise ValueError("template_not_found")

    scenario_id = f"custom-{series_id.hex[:12]}-{version}"
    payload = template.model_dump(mode="json")
    payload["metadata"].update({
        "id": scenario_id,
        "version": 1,
        "version_id": f"{scenario_id}:v1",
        "status": "published",
        "published_at": datetime.now(timezone.utc).isoformat(),
    })
    payload["public_briefing"].update({
        "title": request.title,
        "summary": request.situation,
        "situation": request.situation,
        "objective": request.objective,
        "estimated_minutes": request.estimated_minutes,
    })
    participant_id = payload["public_briefing"]["participant_role_id"]
    participant = next(item for item in payload["roles"] if item["id"] == participant_id)
    opponent = next(item for item in payload["roles"] if item["id"] != participant_id)
    participant["title"] = request.participant_role
    participant["goal"] = request.objective
    opponent["title"] = request.opponent_role
    payload["difficulty"] = {"easy": "beginner", "medium": "intermediate", "hard": "advanced"}[request.difficulty.value]
    payload["tone"] = {"cooperative": "cooperative", "businesslike": "businesslike", "firm": "assertive"}[request.tone.value]
    base_limits = payload["turn_limits"]
    base_limits["maximum"] = request.max_turns
    base_limits["minimum"] = min(int(base_limits["minimum"]), request.max_turns - 1)
    base_limits["warning_at"] = max(base_limits["minimum"], min(int(base_limits["warning_at"]), request.max_turns - 1))
    _scale_primary_issue(payload, {"low": 0.8, "standard": 1.0, "high": 1.2}[request.stakes_level])

    definition = ScenarioDefinition.model_validate_json(json.dumps(payload, ensure_ascii=False))
    validation = simulate_boundaries(definition)
    public = template_public.model_copy(update={
        "id": scenario_id,
        "version": f"draft-{version}",
        "title": request.title,
        "summary": request.situation,
        "context": request.situation,
        "participant_role": request.participant_role,
        "opponent_role": request.opponent_role,
        "objective": request.objective,
        "estimated_minutes": request.estimated_minutes,
        "tone": request.tone.value,
        "difficulty": request.difficulty.value,
        "max_turns": request.max_turns,
        "tasks": participant_tasks(definition),
        "industry": request.industry,
        "negotiation_type": definition.negotiation_type.value,
        "theme": request.theme,
        "role_tags": (request.participant_role, request.opponent_role),
        "source": "custom",
        "revision": version,
    })
    return public, definition, validation


class ScenarioDraftService:
    def __init__(self, catalog: ScenarioCatalog, repository: ScenarioDraftRepository) -> None:
        self.catalog = catalog
        self.repository = repository

    def load_existing(self) -> None:
        for item in self.repository.list_all():
            self.catalog.register_custom(item.scenario, item.definition, str(item.user_id))

    def save(self, user_id: UUID, request: ScenarioDraftRequest) -> ScenarioDraftResponse:
        series_id = request.series_id or uuid4()
        version = self.repository.next_version(user_id, series_id)
        public, definition, validation = compile_draft(self.catalog, request, series_id, version)
        now = datetime.now(timezone.utc)
        draft = StoredScenarioDraft(
            id=uuid4(),
            series_id=series_id,
            user_id=user_id,
            version=version,
            scenario=public,
            definition=definition,
            validation=validation,
            input_payload=request.model_dump(mode="json"),
            created_at=now,
        )
        self.repository.save(draft)
        self.catalog.register_custom(public, definition, str(user_id))
        return draft.response()

    def list_for_user(self, user_id: UUID) -> list[ScenarioDraftResponse]:
        return [item.response() for item in self.repository.list_for_user(user_id)]

    def delete_for_user(self, user_id: UUID) -> None:
        self.repository.delete_for_user(user_id)
        self.catalog.remove_custom_for_user(str(user_id))


__all__ = [
    "InMemoryScenarioDraftRepository",
    "ScenarioDraftRepository",
    "ScenarioDraftService",
    "SqlAlchemyScenarioDraftRepository",
    "compile_draft",
    "simulate_boundaries",
]
