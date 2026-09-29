from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", min_length=2, max_length=64),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
LanguageTag = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}-[A-Z]{2}$")]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class ScenarioStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class NegotiationType(StrEnum):
    PROCUREMENT = "procurement"
    INTERNAL_RESOURCES = "internal_resources"
    SALES = "sales"
    PARTNERSHIP = "partnership"
    CONFLICT = "conflict"


class Difficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Tone(StrEnum):
    COOPERATIVE = "cooperative"
    BUSINESSLIKE = "businesslike"
    ASSERTIVE = "assertive"
    TENSE = "tense"


class MethodologyModule(StrEnum):
    PRINCIPLED_NEGOTIATION = "principled_negotiation"
    SEVEN_ELEMENTS = "seven_elements"
    ACTIVE_LISTENING = "active_listening"
    INTEGRATIVE = "integrative"
    DISTRIBUTIVE = "distributive"
    MESO = "meso"
    SPIN = "spin"
    NVC = "nvc"
    ANCHORING = "anchoring"
    CONTINGENT_AGREEMENT = "contingent_agreement"
    BEHAVIORAL_CHANGE_STAIRWAY = "behavioral_change_stairway"


class PreferenceDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class ConditionOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GTE = "gte"
    LTE = "lte"
    GT = "gt"
    LT = "lt"
    IN = "in"


class DisclosureTrigger(StrEnum):
    OPEN_QUESTION = "open_question"
    ACTIVE_LISTENING = "active_listening"
    TRUST = "trust"
    TURN = "turn"
    RECIPROCAL_DISCLOSURE = "reciprocal_disclosure"


class ScenarioMetadata(DomainModel):
    id: Identifier
    version: int = Field(ge=1)
    version_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]*:v[1-9][0-9]*$")]
    status: ScenarioStatus
    language: LanguageTag
    created_at: datetime
    published_at: datetime | None = None

    @model_validator(mode="after")
    def validate_immutable_identity(self) -> "ScenarioMetadata":
        expected = f"{self.id}:v{self.version}"
        if self.version_id != expected:
            raise ValueError(f"version_id должен быть каноническим и равен {expected}")
        if self.status is ScenarioStatus.PUBLISHED and self.published_at is None:
            raise ValueError("У опубликованной версии должен быть published_at")
        if self.status is ScenarioStatus.DRAFT and self.published_at is not None:
            raise ValueError("Черновик не может иметь published_at")
        if self.published_at is not None and self.published_at < self.created_at:
            raise ValueError("published_at не может быть раньше created_at")
        return self


class PublicBriefing(DomainModel):
    title: NonEmptyText
    summary: NonEmptyText
    situation: NonEmptyText
    participant_role_id: Identifier
    objective: NonEmptyText
    known_facts: tuple[NonEmptyText, ...] = Field(min_length=1)
    agenda: tuple[NonEmptyText, ...] = Field(min_length=1)
    estimated_minutes: int = Field(ge=3, le=120)


class Interest(DomainModel):
    id: Identifier
    description: NonEmptyText
    priority: int = Field(ge=1, le=5)


class Alternative(DomainModel):
    description: NonEmptyText
    utility: int = Field(ge=0, le=100)


class RoleDefinition(DomainModel):
    id: Identifier
    title: NonEmptyText
    organization: NonEmptyText
    goal: NonEmptyText
    aspiration: NonEmptyText
    reservation: NonEmptyText
    batna: Alternative
    explicit_interests: tuple[Interest, ...] = Field(min_length=1)
    hidden_interests: tuple[Interest, ...] = Field(min_length=1)
    authority: NonEmptyText

    @model_validator(mode="after")
    def validate_interest_ids(self) -> "RoleDefinition":
        ids = [item.id for item in (*self.explicit_interests, *self.hidden_interests)]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Интересы роли {self.id} должны иметь уникальные id")
        return self


class PartyIssueRange(DomainModel):
    minimum: float
    maximum: float
    reservation: float
    aspiration: float
    direction: PreferenceDirection

    @model_validator(mode="after")
    def validate_range(self) -> "PartyIssueRange":
        if self.minimum > self.maximum:
            raise ValueError("minimum не может быть больше maximum")
        if not self.minimum <= self.reservation <= self.maximum:
            raise ValueError("reservation должен находиться внутри диапазона")
        if not self.minimum <= self.aspiration <= self.maximum:
            raise ValueError("aspiration должен находиться внутри диапазона")
        if self.direction is PreferenceDirection.MAXIMIZE and self.aspiration < self.reservation:
            raise ValueError("При maximize aspiration должен быть не меньше reservation")
        if self.direction is PreferenceDirection.MINIMIZE and self.aspiration > self.reservation:
            raise ValueError("При minimize aspiration должен быть не больше reservation")
        return self


class IssueDefinition(DomainModel):
    id: Identifier
    title: NonEmptyText
    description: NonEmptyText
    unit: NonEmptyText
    party_weights: dict[Identifier, float] = Field(min_length=2)
    party_ranges: dict[Identifier, PartyIssueRange] = Field(min_length=2)

    @field_validator("party_weights")
    @classmethod
    def weights_must_be_positive(cls, value: dict[str, float]) -> dict[str, float]:
        if any(weight <= 0 or weight > 100 for weight in value.values()):
            raise ValueError("Вес вопроса для каждой стороны должен быть в диапазоне (0, 100]")
        return value


class ZopaOverlap(DomainModel):
    status: Literal["overlap"]
    issue_id: Identifier
    lower: float
    upper: float

    @model_validator(mode="after")
    def validate_bounds(self) -> "ZopaOverlap":
        if self.lower > self.upper:
            raise ValueError("Нижняя граница ZOPA не может быть больше верхней")
        return self


class ZopaNoOverlap(DomainModel):
    status: Literal["no_overlap"]
    issue_id: Identifier
    explanation: NonEmptyText


ZopaDefinition = Annotated[ZopaOverlap | ZopaNoOverlap, Field(discriminator="status")]


class ObjectiveCriterion(DomainModel):
    id: Identifier
    title: NonEmptyText
    description: NonEmptyText
    source: NonEmptyText
    issue_ids: tuple[Identifier, ...] = Field(min_length=1)


class InitialState(DomainModel):
    trust: int = Field(ge=0, le=100)
    tension: int = Field(ge=0, le=100)
    progress: int = Field(ge=0, le=100)
    relationship: int = Field(ge=0, le=100)
    concession_budget: dict[Identifier, float] = Field(min_length=2)

    @field_validator("concession_budget")
    @classmethod
    def budget_must_be_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        if any(amount < 0 for amount in value.values()):
            raise ValueError("Бюджет уступок не может быть отрицательным")
        return value


class DisclosureRule(DomainModel):
    id: Identifier
    owner_role_id: Identifier
    hidden_interest_id: Identifier
    trigger: DisclosureTrigger
    threshold: int = Field(ge=1, le=100)
    reveal_message: NonEmptyText


class OfferTemplate(DomainModel):
    id: Identifier
    title: NonEmptyText
    proposer_role_id: Identifier
    values: dict[Identifier, float] = Field(min_length=1)
    equivalent_group: Identifier | None = None


class TradeOption(DomainModel):
    id: Identifier
    beneficiary_role_id: Identifier
    give_issue_id: Identifier
    receive_issue_id: Identifier
    rationale: NonEmptyText
    conditional: bool = False


class ConditionPredicate(DomainModel):
    metric: Identifier
    operator: ConditionOperator
    value: str | float | int | bool
    role_id: Identifier | None = None
    issue_id: Identifier | None = None


class ConditionDefinition(DomainModel):
    id: Identifier
    description: NonEmptyText
    match: Literal["all", "any"] = "all"
    predicates: tuple[ConditionPredicate, ...] = Field(min_length=1)


class TurnLimits(DomainModel):
    minimum: int = Field(ge=1, le=100)
    warning_at: int = Field(ge=1, le=100)
    maximum: int = Field(ge=2, le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "TurnLimits":
        if not self.minimum <= self.warning_at < self.maximum:
            raise ValueError("Должно выполняться minimum <= warning_at < maximum")
        return self


_UNIVERSAL_METHODS = {
    MethodologyModule.PRINCIPLED_NEGOTIATION,
    MethodologyModule.SEVEN_ELEMENTS,
    MethodologyModule.ACTIVE_LISTENING,
}
_TYPE_METHODS: dict[NegotiationType, set[MethodologyModule]] = {
    NegotiationType.PROCUREMENT: {
        *_UNIVERSAL_METHODS,
        MethodologyModule.INTEGRATIVE,
        MethodologyModule.DISTRIBUTIVE,
        MethodologyModule.MESO,
        MethodologyModule.ANCHORING,
        MethodologyModule.CONTINGENT_AGREEMENT,
    },
    NegotiationType.INTERNAL_RESOURCES: {
        *_UNIVERSAL_METHODS,
        MethodologyModule.INTEGRATIVE,
        MethodologyModule.DISTRIBUTIVE,
        MethodologyModule.SPIN,
        MethodologyModule.MESO,
    },
    NegotiationType.SALES: {
        *_UNIVERSAL_METHODS,
        MethodologyModule.INTEGRATIVE,
        MethodologyModule.DISTRIBUTIVE,
        MethodologyModule.SPIN,
        MethodologyModule.MESO,
        MethodologyModule.ANCHORING,
        MethodologyModule.CONTINGENT_AGREEMENT,
    },
    NegotiationType.PARTNERSHIP: {
        *_UNIVERSAL_METHODS,
        MethodologyModule.INTEGRATIVE,
        MethodologyModule.MESO,
        MethodologyModule.CONTINGENT_AGREEMENT,
    },
    NegotiationType.CONFLICT: {
        *_UNIVERSAL_METHODS,
        MethodologyModule.NVC,
        MethodologyModule.BEHAVIORAL_CHANGE_STAIRWAY,
    },
}


class ScenarioDefinition(DomainModel):
    """Complete, versioned source of truth for one negotiation scenario."""

    schema_version: Literal["1.0"]
    metadata: ScenarioMetadata
    negotiation_type: NegotiationType
    public_briefing: PublicBriefing
    roles: tuple[RoleDefinition, ...] = Field(min_length=2, max_length=2)
    issues: tuple[IssueDefinition, ...] = Field(min_length=1)
    zopa: tuple[ZopaDefinition, ...] = Field(min_length=1)
    objective_criteria: tuple[ObjectiveCriterion, ...] = Field(min_length=1)
    initial_state: InitialState
    tone: Tone
    difficulty: Difficulty
    methodology_modules: tuple[MethodologyModule, ...] = Field(min_length=3)
    disclosure_rules: tuple[DisclosureRule, ...] = Field(min_length=1)
    offer_templates: tuple[OfferTemplate, ...] = Field(min_length=1)
    trade_options: tuple[TradeOption, ...] = Field(min_length=1)
    success_conditions: tuple[ConditionDefinition, ...] = Field(min_length=1)
    impasse_conditions: tuple[ConditionDefinition, ...] = Field(min_length=1)
    walk_away_conditions: tuple[ConditionDefinition, ...] = Field(min_length=1)
    turn_limits: TurnLimits
    rubric_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+$")]

    @model_validator(mode="after")
    def validate_graph(self) -> "ScenarioDefinition":
        role_ids = [role.id for role in self.roles]
        issue_ids = [issue.id for issue in self.issues]
        self._require_unique("roles", role_ids)
        self._require_unique("issues", issue_ids)
        self._require_unique("zopa", [item.issue_id for item in self.zopa])
        self._require_unique("objective_criteria", [item.id for item in self.objective_criteria])
        self._require_unique("disclosure_rules", [item.id for item in self.disclosure_rules])
        self._require_unique("offer_templates", [item.id for item in self.offer_templates])
        self._require_unique("trade_options", [item.id for item in self.trade_options])
        conditions = (*self.success_conditions, *self.impasse_conditions, *self.walk_away_conditions)
        self._require_unique("conditions", [item.id for item in conditions])
        self._require_unique("methodology_modules", [item.value for item in self.methodology_modules])

        role_set, issue_set = set(role_ids), set(issue_ids)
        if self.public_briefing.participant_role_id not in role_set:
            raise ValueError("participant_role_id должен ссылаться на роль сценария")

        for issue in self.issues:
            if set(issue.party_weights) != role_set or set(issue.party_ranges) != role_set:
                raise ValueError(f"Вопрос {issue.id} должен иметь веса и диапазоны для всех ролей")
        for role_id in role_ids:
            total = sum(issue.party_weights[role_id] for issue in self.issues)
            if abs(total - 100.0) > 1e-6:
                raise ValueError(f"Сумма весов вопросов для роли {role_id} должна быть равна 100")
        if {item.issue_id for item in self.zopa} != issue_set:
            raise ValueError("ZOPA должна содержать все и только вопросы сценария")
        for zopa_item in self.zopa:
            issue = next(item for item in self.issues if item.id == zopa_item.issue_id)
            domain_lower = max(item.minimum for item in issue.party_ranges.values())
            domain_upper = min(item.maximum for item in issue.party_ranges.values())
            lower = max(
                [
                    domain_lower,
                    *(
                        item.reservation
                        for item in issue.party_ranges.values()
                        if item.direction is PreferenceDirection.MAXIMIZE
                    ),
                ]
            )
            upper = min(
                [
                    domain_upper,
                    *(
                        item.reservation
                        for item in issue.party_ranges.values()
                        if item.direction is PreferenceDirection.MINIMIZE
                    ),
                ]
            )
            has_overlap = lower <= upper
            if isinstance(zopa_item, ZopaNoOverlap):
                if has_overlap:
                    raise ValueError(f"ZOPA вопроса {issue.id} объявлена отсутствующей, но диапазоны пересекаются")
            elif not has_overlap:
                raise ValueError(f"ZOPA вопроса {issue.id} должна быть явно объявлена как no_overlap")
            elif abs(zopa_item.lower - lower) > 1e-6 or abs(zopa_item.upper - upper) > 1e-6:
                raise ValueError(f"Границы ZOPA вопроса {issue.id} не соответствуют reservation point сторон")
        if set(self.initial_state.concession_budget) != role_set:
            raise ValueError("concession_budget должен содержать все и только роли сценария")

        for criterion in self.objective_criteria:
            self._require_subset(f"criterion {criterion.id}", criterion.issue_ids, issue_set)
        hidden_ids_by_role = {
            role.id: {interest.id for interest in role.hidden_interests} for role in self.roles
        }
        for rule in self.disclosure_rules:
            if rule.owner_role_id not in role_set:
                raise ValueError(f"Правило {rule.id} ссылается на неизвестную роль")
            if rule.hidden_interest_id not in hidden_ids_by_role[rule.owner_role_id]:
                raise ValueError(f"Правило {rule.id} должно ссылаться на скрытый интерес своей роли")
        for offer in self.offer_templates:
            if offer.proposer_role_id not in role_set:
                raise ValueError(f"Предложение {offer.id} ссылается на неизвестную роль")
            self._require_subset(f"offer {offer.id}", offer.values.keys(), issue_set)
            for issue_id, value in offer.values.items():
                issue = next(item for item in self.issues if item.id == issue_id)
                lower = min(item.minimum for item in issue.party_ranges.values())
                upper = max(item.maximum for item in issue.party_ranges.values())
                if not lower <= value <= upper:
                    raise ValueError(f"Значение {issue_id} в предложении {offer.id} вне диапазона сценария")
        for trade in self.trade_options:
            if trade.beneficiary_role_id not in role_set:
                raise ValueError(f"Обмен {trade.id} ссылается на неизвестную роль")
            self._require_subset(f"trade {trade.id}", (trade.give_issue_id, trade.receive_issue_id), issue_set)
            if trade.give_issue_id == trade.receive_issue_id:
                raise ValueError(f"Обмен {trade.id} должен связывать два разных вопроса")
        for condition in conditions:
            for predicate in condition.predicates:
                if predicate.role_id is not None and predicate.role_id not in role_set:
                    raise ValueError(f"Условие {condition.id} ссылается на неизвестную роль")
                if predicate.issue_id is not None and predicate.issue_id not in issue_set:
                    raise ValueError(f"Условие {condition.id} ссылается на неизвестный вопрос")

        modules = set(self.methodology_modules)
        if not _UNIVERSAL_METHODS <= modules:
            raise ValueError("Сценарий должен включать универсальное методическое ядро")
        invalid = modules - _TYPE_METHODS[self.negotiation_type]
        if invalid:
            names = ", ".join(sorted(module.value for module in invalid))
            raise ValueError(f"Методы не применимы к типу {self.negotiation_type.value}: {names}")
        if MethodologyModule.MESO in modules:
            groups: dict[str, int] = {}
            for offer in self.offer_templates:
                if offer.equivalent_group:
                    groups[offer.equivalent_group] = groups.get(offer.equivalent_group, 0) + 1
            if not any(count >= 2 for count in groups.values()):
                raise ValueError("MESO требует минимум два предложения в одной equivalent_group")
        if MethodologyModule.CONTINGENT_AGREEMENT in modules and not any(
            trade.conditional for trade in self.trade_options
        ):
            raise ValueError("Условное соглашение требует хотя бы один conditional trade")

        self._validate_no_hidden_data_in_public_briefing()
        return self

    @staticmethod
    def _require_unique(name: str, values: list[str]) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"{name}: id должны быть уникальны")

    @staticmethod
    def _require_subset(name: str, values: Any, allowed: set[str]) -> None:
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"{name} содержит неизвестные ссылки: {', '.join(sorted(unknown))}")

    @staticmethod
    def _normalize_secret(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold()).strip(" .,:;!?")

    def _validate_no_hidden_data_in_public_briefing(self) -> None:
        public_text = self._normalize_secret(
            " ".join(
                (
                    self.public_briefing.title,
                    self.public_briefing.summary,
                    self.public_briefing.situation,
                    self.public_briefing.objective,
                    *self.public_briefing.known_facts,
                    *self.public_briefing.agenda,
                )
            )
        )
        secrets = []
        for role in self.roles:
            secrets.extend(item.description for item in role.hidden_interests)
            secrets.extend((role.batna.description, role.reservation))
        for secret in secrets:
            normalized = self._normalize_secret(secret)
            if len(normalized) >= 8 and normalized in public_text:
                raise ValueError("Публичный брифинг содержит скрытые данные роли")
