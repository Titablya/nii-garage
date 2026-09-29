from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..domain.scenario import Identifier


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ScenarioVersionId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9._-]*:v[1-9][0-9]*$", max_length=80),
]


class EngineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class ActionTag(StrEnum):
    OPEN_QUESTION = "open_question"
    ACTIVE_LISTENING = "active_listening"
    OBJECTIVE_CRITERION = "objective_criterion"
    OPTION = "option"
    MESO = "meso"
    ANCHOR = "anchor"
    CONDITIONAL_AGREEMENT = "conditional_agreement"
    COMMITMENT = "commitment"
    PERSONAL_ATTACK = "personal_attack"
    THREAT = "threat"
    UNILATERAL_CONCESSION = "unilateral_concession"
    ACCEPT = "accept"
    REJECT = "reject"
    WALK_AWAY = "walk_away"


class NegotiationStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


class NegotiationOutcome(StrEnum):
    AGREEMENT = "agreement"
    IMPASSE = "impasse"
    WALK_AWAY = "walk_away"


class DirectiveKind(StrEnum):
    ACCEPT = "accept"
    COUNTER = "counter"
    CLARIFY = "clarify"
    IMPASSE = "impasse"
    WALK_AWAY = "walk_away"


class ReasonCode(StrEnum):
    TURN_PROCESSED = "turn.processed"
    TURN_WARNING = "turn.warning"
    TURN_LIMIT_REACHED = "turn.limit_reached"
    TERMINAL_STATE_IGNORED = "turn.terminal_state_ignored"
    OPEN_QUESTION_DETECTED = "action.open_question"
    ACTIVE_LISTENING_DETECTED = "action.active_listening"
    OBJECTIVE_CRITERION_DETECTED = "action.objective_criterion"
    OPTION_DETECTED = "action.option"
    MESO_DETECTED = "action.meso"
    ANCHOR_DETECTED = "action.anchor"
    CONDITIONAL_AGREEMENT_DETECTED = "action.conditional_agreement"
    COMMITMENT_DETECTED = "action.commitment"
    PERSONAL_ATTACK_DETECTED = "action.personal_attack"
    THREAT_DETECTED = "action.threat"
    UNILATERAL_CONCESSION_DETECTED = "action.unilateral_concession"
    ACCEPT_DETECTED = "action.accept"
    REJECT_DETECTED = "action.reject"
    WALK_AWAY_DETECTED = "action.walk_away"
    OFFER_EXTRACTED = "offer.extracted"
    OFFER_IN_ZOPA = "offer.in_zopa"
    OFFER_OUTSIDE_ZOPA = "offer.outside_zopa"
    OFFER_RESERVATION_VIOLATION = "offer.reservation_violation"
    OFFER_BELOW_BATNA = "offer.below_batna"
    OFFER_INCOMPLETE = "offer.incomplete"
    INTEREST_DISCLOSED = "disclosure.triggered"
    AGREEMENT_REACHED = "outcome.agreement"
    IMPASSE_REACHED = "outcome.impasse"
    WALK_AWAY_REACHED = "outcome.walk_away"
    WALK_AWAY_CONDITION_MATCHED = "condition.walk_away_matched"
    COMMITMENT_REQUIRED = "condition.commitment_required"
    COUNTER_OFFER_CREATED = "directive.counter_offer_created"
    CLARIFICATION_REQUESTED = "directive.clarification_requested"


class IssueValue(EngineModel):
    issue_id: Identifier
    value: float


class NegotiationOffer(EngineModel):
    proposer_role_id: Identifier
    values: tuple[IssueValue, ...] = Field(min_length=1)
    source_turn: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_values(self) -> "NegotiationOffer":
        ids = [item.issue_id for item in self.values]
        if ids != sorted(ids):
            raise ValueError("Offer values must be sorted by issue_id")
        if len(ids) != len(set(ids)):
            raise ValueError("Offer issue IDs must be unique")
        return self


class RoleBudget(EngineModel):
    role_id: Identifier
    remaining: float = Field(ge=0, le=100)


class PreliminaryCommitment(EngineModel):
    turn: int = Field(ge=1)
    role_id: Identifier
    text: NonEmpty


class NegotiationState(EngineModel):
    schema_version: Literal["1.0"] = "1.0"
    scenario_version_id: ScenarioVersionId
    participant_role_id: Identifier
    opponent_role_id: Identifier
    trust: int = Field(ge=0, le=100)
    tension: int = Field(ge=0, le=100)
    progress: int = Field(ge=0, le=100)
    relationship: int = Field(ge=0, le=100)
    turn_count: int = Field(ge=0)
    disclosed_interest_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    concession_budget: tuple[RoleBudget, ...] = Field(min_length=2, max_length=2)
    current_offer: NegotiationOffer | None = None
    accepted_offer: NegotiationOffer | None = None
    preliminary_commitments: tuple[PreliminaryCommitment, ...] = Field(default_factory=tuple)
    status: NegotiationStatus = NegotiationStatus.ACTIVE
    outcome: NegotiationOutcome | None = None
    open_question_count: int = Field(default=0, ge=0)
    active_listening_count: int = Field(default=0, ge=0)
    stagnant_turns: int = Field(default=0, ge=0)
    last_action_signature: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "NegotiationState":
        if self.participant_role_id == self.opponent_role_id:
            raise ValueError("Participant and opponent roles must differ")
        disclosed = list(self.disclosed_interest_ids)
        if disclosed != sorted(disclosed) or len(disclosed) != len(set(disclosed)):
            raise ValueError("disclosed_interest_ids must be sorted and unique")
        budget_roles = [item.role_id for item in self.concession_budget]
        if budget_roles != sorted(budget_roles) or len(set(budget_roles)) != 2:
            raise ValueError("concession_budget must contain two sorted unique roles")
        if self.status is NegotiationStatus.ACTIVE and self.outcome is not None:
            raise ValueError("Active negotiation cannot have an outcome")
        if self.status is NegotiationStatus.COMPLETED and self.outcome is None:
            raise ValueError("Completed negotiation must have an outcome")
        if self.outcome is NegotiationOutcome.AGREEMENT and self.accepted_offer is None:
            raise ValueError("Agreement must reference accepted_offer")
        if self.accepted_offer is not None and self.outcome is not NegotiationOutcome.AGREEMENT:
            raise ValueError("accepted_offer is only valid for agreement")
        return self


class ClassifiedAction(EngineModel):
    normalized_text: NonEmpty
    tags: tuple[ActionTag, ...] = Field(default_factory=tuple)
    issue_values: tuple[IssueValue, ...] = Field(default_factory=tuple)
    objective_criterion_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    signature: NonEmpty

    @model_validator(mode="after")
    def validate_canonical_order(self) -> "ClassifiedAction":
        if list(self.tags) != sorted(self.tags, key=lambda item: item.value):
            raise ValueError("Action tags must be sorted")
        issue_ids = [item.issue_id for item in self.issue_values]
        if issue_ids != sorted(issue_ids) or len(issue_ids) != len(set(issue_ids)):
            raise ValueError("Action issue values must be sorted and unique")
        criterion_ids = list(self.objective_criterion_ids)
        if criterion_ids != sorted(criterion_ids) or len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Criterion IDs must be sorted and unique")
        return self


class ReservationViolation(EngineModel):
    role_id: Identifier
    issue_id: Identifier
    value: float


class RoleUtility(EngineModel):
    role_id: Identifier
    utility: float = Field(ge=0, le=100)
    batna_utility: int = Field(ge=0, le=100)
    meets_batna: bool


class OfferAssessment(EngineModel):
    complete: bool
    acceptable_for_all: bool
    zopa_violation_issue_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    reservation_violations: tuple[ReservationViolation, ...] = Field(default_factory=tuple)
    role_utilities: tuple[RoleUtility, ...] = Field(default_factory=tuple)


class EngineEvent(EngineModel):
    sequence: int = Field(ge=1)
    code: ReasonCode
    action_tag: ActionTag | None = None
    issue_id: Identifier | None = None
    value: float | None = None


class OpponentDirective(EngineModel):
    kind: DirectiveKind
    template_key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]+$")]
    offer: NegotiationOffer | None = None
    public_facts: tuple[NonEmpty, ...] = Field(default_factory=tuple)
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)


class Transition(EngineModel):
    schema_version: Literal["1.0"] = "1.0"
    scenario_version_id: ScenarioVersionId
    from_turn: int = Field(ge=0)
    to_turn: int = Field(ge=0)
    action: ClassifiedAction
    state: NegotiationState
    events: tuple[EngineEvent, ...] = Field(min_length=1)
    directive: OpponentDirective

    @model_validator(mode="after")
    def validate_transition(self) -> "Transition":
        if self.scenario_version_id != self.state.scenario_version_id:
            raise ValueError("Transition and state scenario versions must match")
        if self.to_turn != self.state.turn_count:
            raise ValueError("to_turn must match state.turn_count")
        sequences = [event.sequence for event in self.events]
        if sequences != list(range(1, len(self.events) + 1)):
            raise ValueError("Event sequence must be contiguous")
        return self
