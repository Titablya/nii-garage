from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, selectinload

from .db.database import Database
from .db.models import (
    EvaluationRun,
    MessageRecord,
    NegotiationSession as NegotiationSessionRecord,
    Scenario as ScenarioRecord,
    ScenarioVersion as ScenarioVersionRecord,
    SessionStateEvent,
)
from .engine import EngineEvent, NegotiationState
from .models import (
    Message,
    NegotiationSession,
    ReportResponse,
    SessionConfiguration,
    SimulationState,
    SessionStatus,
)
from .scenario_catalog import ScenarioCatalog


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class SessionRepository(Protocol):
    """Persistence boundary used by the negotiation application service."""

    def create(self, session: NegotiationSession) -> NegotiationSession: ...

    def get(self, session_id: UUID) -> NegotiationSession | None: ...

    def save(self, session: NegotiationSession) -> NegotiationSession: ...

    def list_completed(self) -> tuple[NegotiationSession, ...]: ...

    def list_series(self, series_id: UUID) -> tuple[NegotiationSession, ...]: ...

    def list_for_user(self, user_id: UUID) -> tuple[NegotiationSession, ...]: ...

    def claim(self, session_id: UUID, user_id: UUID) -> NegotiationSession: ...

    def delete_for_user(self, user_id: UUID) -> None: ...

    def get_report(self, session_id: UUID) -> ReportResponse | None: ...

    def save_report(self, report: ReportResponse) -> ReportResponse: ...

    def ping(self) -> bool: ...


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[UUID, NegotiationSession] = {}
        self._reports: dict[UUID, ReportResponse] = {}

    def create(self, session: NegotiationSession) -> NegotiationSession:
        self._sessions[session.id] = session
        return session

    def get(self, session_id: UUID) -> NegotiationSession | None:
        return self._sessions.get(session_id)

    def save(self, session: NegotiationSession) -> NegotiationSession:
        self._sessions[session.id] = session
        return session

    def list_completed(self) -> tuple[NegotiationSession, ...]:
        return tuple(
            session for session in self._sessions.values() if session.status.value == "completed"
        )

    def list_series(self, series_id: UUID) -> tuple[NegotiationSession, ...]:
        return tuple(
            sorted(
                (session for session in self._sessions.values() if session.series_id == series_id),
                key=lambda session: session.attempt_number,
            )
        )

    def list_for_user(self, user_id: UUID) -> tuple[NegotiationSession, ...]:
        return tuple(
            sorted(
                (session for session in self._sessions.values() if session.participant_user_id == user_id),
                key=lambda session: session.created_at,
                reverse=True,
            )
        )

    def claim(self, session_id: UUID, user_id: UUID) -> NegotiationSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("session_not_found")
        if session.participant_user_id not in {None, user_id}:
            raise ValueError("session_already_claimed")
        session.participant_user_id = user_id
        return session

    def delete_for_user(self, user_id: UUID) -> None:
        ids = {session.id for session in self._sessions.values() if session.participant_user_id == user_id}
        self._sessions = {key: value for key, value in self._sessions.items() if key not in ids}
        self._reports = {key: value for key, value in self._reports.items() if key not in ids}

    def get_report(self, session_id: UUID) -> ReportResponse | None:
        report = self._reports.get(session_id)
        return report.model_copy(deep=True) if report is not None else None

    def save_report(self, report: ReportResponse) -> ReportResponse:
        existing = self._reports.get(report.session_id)
        if existing is not None:
            return existing.model_copy(deep=True)
        self._reports[report.session_id] = report.model_copy(deep=True)
        return report.model_copy(deep=True)

    def ping(self) -> bool:
        return True


class SqlAlchemySessionRepository:
    """PostgreSQL-backed runtime repository with immutable state snapshots."""

    def __init__(self, database: Database, scenario_catalog: ScenarioCatalog) -> None:
        self._database = database
        self._scenario_catalog = scenario_catalog

    def create(self, session: NegotiationSession) -> NegotiationSession:
        with self._database.session_factory.begin() as db:
            self._ensure_scenario_version(db, session)
            if db.get(NegotiationSessionRecord, str(session.id)) is not None:
                raise ValueError("session_already_exists")
            row = NegotiationSessionRecord(
                id=str(session.id),
                series_id=str(session.series_id),
                previous_session_id=(
                    str(session.previous_session_id) if session.previous_session_id else None
                ),
                attempt_number=session.attempt_number,
                scenario_version_id=session.scenario_version_id,
                participant_user_id=(str(session.participant_user_id) if session.participant_user_id else None),
                status=session.status.value,
                started_at=session.created_at,
                completed_at=session.completed_at,
                scenario_snapshot={
                    "scenario_id": session.scenario_id,
                    "scenario_version_id": session.scenario_version_id,
                    "configuration": session.configuration.model_dump(mode="json"),
                },
                simulation_snapshot=session.simulation_state.model_dump(mode="json"),
                created_at=session.created_at,
            )
            row.messages = self._message_rows(session)
            row.state_events = [self._state_event(session, sequence=1, event_type="session.created")]
            db.add(row)
        return session

    def get(self, session_id: UUID) -> NegotiationSession | None:
        with self._database.session_factory() as db:
            row = self._load_row(db, session_id)
            return self._to_domain(row) if row is not None else None

    def save(self, session: NegotiationSession) -> NegotiationSession:
        with self._database.session_factory.begin() as db:
            statement = (
                self._base_query()
                .where(NegotiationSessionRecord.id == str(session.id))
                .with_for_update()
            )
            row = db.scalar(statement)
            if row is None:
                raise KeyError("session_not_found")
            row.status = session.status.value
            row.completed_at = session.completed_at
            row.simulation_snapshot = session.simulation_state.model_dump(mode="json")

            existing_message_ids = {item.id for item in row.messages}
            next_sequence = max((item.sequence_number for item in row.messages), default=0) + 1
            for message in session.messages:
                if str(message.id) in existing_message_ids:
                    continue
                row.messages.append(
                    MessageRecord(
                        id=str(message.id),
                        sequence_number=next_sequence,
                        author_type=message.role,
                        content=message.content,
                        metadata_json={
                            "speaker_id": message.speaker_id,
                            "speaker_label": message.speaker_label,
                            "message_kind": message.message_kind,
                        },
                        created_at=message.created_at,
                    )
                )
                next_sequence += 1

            event_sequence = max(
                (item.sequence_number for item in row.state_events), default=0
            ) + 1
            event_type = (
                "session.completed"
                if session.status is SessionStatus.COMPLETED
                else "session.updated"
            )
            row.state_events.append(
                self._state_event(session, sequence=event_sequence, event_type=event_type)
            )
        return session

    def list_completed(self) -> tuple[NegotiationSession, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                self._base_query()
                .where(NegotiationSessionRecord.status == SessionStatus.COMPLETED.value)
                .order_by(NegotiationSessionRecord.completed_at.desc())
            ).all()
            return tuple(self._to_domain(row) for row in rows)

    def list_series(self, series_id: UUID) -> tuple[NegotiationSession, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                self._base_query()
                .where(NegotiationSessionRecord.series_id == str(series_id))
                .order_by(NegotiationSessionRecord.attempt_number)
            ).all()
            return tuple(self._to_domain(row) for row in rows)

    def list_for_user(self, user_id: UUID) -> tuple[NegotiationSession, ...]:
        with self._database.session_factory() as db:
            rows = db.scalars(
                self._base_query()
                .where(NegotiationSessionRecord.participant_user_id == str(user_id))
                .order_by(NegotiationSessionRecord.started_at.desc())
            ).all()
            return tuple(self._to_domain(row) for row in rows)

    def claim(self, session_id: UUID, user_id: UUID) -> NegotiationSession:
        with self._database.session_factory.begin() as db:
            row = db.scalar(
                self._base_query()
                .where(NegotiationSessionRecord.id == str(session_id))
                .with_for_update()
            )
            if row is None:
                raise KeyError("session_not_found")
            if row.participant_user_id not in {None, str(user_id)}:
                raise ValueError("session_already_claimed")
            row.participant_user_id = str(user_id)
            db.flush()
            return self._to_domain(row)

    def delete_for_user(self, user_id: UUID) -> None:
        with self._database.session_factory.begin() as db:
            db.execute(
                delete(NegotiationSessionRecord).where(
                    NegotiationSessionRecord.participant_user_id == str(user_id)
                )
            )

    def get_report(self, session_id: UUID) -> ReportResponse | None:
        with self._database.session_factory() as db:
            row = db.scalar(
                select(EvaluationRun)
                .where(
                    EvaluationRun.session_id == str(session_id),
                    EvaluationRun.status == "completed",
                )
                .order_by(EvaluationRun.created_at.asc(), EvaluationRun.id.asc())
                .limit(1)
            )
            if row is None:
                return None
            return self._stored_report(row)

    def save_report(self, report: ReportResponse) -> ReportResponse:
        now = datetime.now(timezone.utc)
        with self._database.session_factory.begin() as db:
            # Serialize concurrent first writes for a session on PostgreSQL.
            db.scalar(
                select(NegotiationSessionRecord.id)
                .where(NegotiationSessionRecord.id == str(report.session_id))
                .with_for_update()
            )
            existing = db.scalar(
                select(EvaluationRun)
                .where(
                    EvaluationRun.session_id == str(report.session_id),
                    EvaluationRun.status == "completed",
                )
                .order_by(EvaluationRun.created_at.asc(), EvaluationRun.id.asc())
                .limit(1)
            )
            if existing is not None:
                return self._stored_report(existing)
            db.add(
                EvaluationRun(
                    session_id=str(report.session_id),
                    evaluator_version=report.evaluator_version,
                    status="completed",
                    score=report.score,
                    result=report.model_dump(mode="json"),
                    started_at=now,
                    completed_at=now,
                    created_at=now,
                )
            )
        return report

    @staticmethod
    def _stored_report(row: EvaluationRun) -> ReportResponse:
        if row.result is None:
            raise ValueError("stored_report_missing")
        report = ReportResponse.model_validate(row.result)
        if (
            report.session_id != UUID(row.session_id)
            or report.evaluator_version != row.evaluator_version
            or report.score != row.score
        ):
            raise ValueError("stored_report_metadata_mismatch")
        return report

    def ping(self) -> bool:
        try:
            with self._database.session_factory() as db:
                db.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def _base_query(self):
        return select(NegotiationSessionRecord).options(
            selectinload(NegotiationSessionRecord.messages),
            selectinload(NegotiationSessionRecord.state_events),
            selectinload(NegotiationSessionRecord.scenario_version).selectinload(
                ScenarioVersionRecord.scenario
            ),
        )

    def _load_row(
        self, db: Session, session_id: UUID
    ) -> NegotiationSessionRecord | None:
        return db.scalar(
            self._base_query().where(NegotiationSessionRecord.id == str(session_id))
        )

    @staticmethod
    def _message_rows(session: NegotiationSession) -> list[MessageRecord]:
        return [
            MessageRecord(
                id=str(message.id),
                sequence_number=index,
                author_type=message.role,
                content=message.content,
                metadata_json={
                    "speaker_id": message.speaker_id,
                    "speaker_label": message.speaker_label,
                    "message_kind": message.message_kind,
                },
                created_at=message.created_at,
            )
            for index, message in enumerate(session.messages, start=1)
        ]

    @staticmethod
    def _state_event(
        session: NegotiationSession, *, sequence: int, event_type: str
    ) -> SessionStateEvent:
        return SessionStateEvent(
            sequence_number=sequence,
            event_type=event_type,
            payload={
                "engine_state": session.engine_state.model_dump(mode="json"),
                "reason_events": [item.model_dump(mode="json") for item in session.reason_events],
            },
        )

    @staticmethod
    def _to_domain(row: NegotiationSessionRecord) -> NegotiationSession:
        if not row.state_events:
            raise ValueError(f"session {row.id} has no state snapshot")
        latest_state = max(row.state_events, key=lambda item: item.sequence_number).payload
        snapshot = row.scenario_snapshot or {}
        configuration_payload = snapshot.get("configuration")
        if configuration_payload is None:
            raise ValueError(f"session {row.id} has no configuration snapshot")
        scenario_id = snapshot.get("scenario_id") or row.scenario_version.scenario.slug
        return NegotiationSession(
            id=UUID(row.id),
            series_id=UUID(row.series_id),
            previous_session_id=(UUID(row.previous_session_id) if row.previous_session_id else None),
            attempt_number=row.attempt_number,
            participant_user_id=(UUID(row.participant_user_id) if row.participant_user_id else None),
            scenario_id=scenario_id,
            scenario_version_id=row.scenario_version_id,
            configuration=SessionConfiguration.model_validate(configuration_payload),
            simulation_state=SimulationState.model_validate(row.simulation_snapshot or {}),
            engine_state=NegotiationState.model_validate_json(
                json.dumps(latest_state["engine_state"])
            ),
            reason_events=[
                EngineEvent.model_validate_json(json.dumps(item))
                for item in latest_state.get("reason_events", [])
            ],
            status=SessionStatus(row.status),
            messages=[
                Message(
                    id=UUID(message.id),
                    role=message.author_type,
                    content=message.content,
                    speaker_id=(message.metadata_json or {}).get("speaker_id"),
                    speaker_label=(message.metadata_json or {}).get("speaker_label"),
                    message_kind=(message.metadata_json or {}).get("message_kind", "dialogue"),
                    created_at=_as_utc(message.created_at),
                )
                for message in sorted(row.messages, key=lambda item: item.sequence_number)
            ],
            created_at=_as_utc(row.started_at),
            completed_at=_as_utc(row.completed_at),
        )

    def _ensure_scenario_version(
        self, db: Session, session: NegotiationSession
    ) -> None:
        scenario = db.get(ScenarioRecord, session.scenario_id)
        public = self._scenario_catalog.get(session.scenario_id)
        definition = self._scenario_catalog.get_definition(session.scenario_id)
        if public is None or definition is None:
            raise KeyError("scenario_not_found")
        if scenario is None:
            scenario = ScenarioRecord(
                id=session.scenario_id,
                slug=session.scenario_id,
                title=public.title,
                summary=public.summary,
            )
            db.add(scenario)
            db.flush()
        version = db.get(ScenarioVersionRecord, session.scenario_version_id)
        if version is None:
            match = re.search(r":v([1-9][0-9]*)$", session.scenario_version_id)
            if match is None:
                raise ValueError("invalid_scenario_version")
            definition_payload = definition.model_dump(mode="json")
            db.add(
                ScenarioVersionRecord(
                    id=session.scenario_version_id,
                    scenario_id=scenario.id,
                    version_number=int(match.group(1)),
                    status="published",
                    definition=definition_payload,
                    immutable_snapshot=definition_payload,
                    published_at=datetime.now(timezone.utc),
                )
            )
