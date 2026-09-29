from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .engine import EngineEvent, NegotiationOutcome, NegotiationState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


class SessionDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SessionTone(StrEnum):
    COOPERATIVE = "cooperative"
    BUSINESSLIKE = "businesslike"
    FIRM = "firm"


class InteractionMode(StrEnum):
    MEETING = "meeting"
    CORRESPONDENCE = "correspondence"
    ESCALATION = "escalation"


class OpponentStrategy(StrEnum):
    ANALYTICAL = "analytical"
    COLLABORATIVE = "collaborative"
    COMPETITIVE = "competitive"
    CAUTIOUS = "cautious"


class NegotiationPhase(StrEnum):
    PREPARATION = "preparation"
    OPENING = "opening"
    EXPLORATION = "exploration"
    EXCHANGE = "exchange"
    COMMITMENT = "commitment"


class SimulationSettings(BaseModel):
    """Public advanced-simulation controls captured with the session."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    enabled: bool = True
    mode: InteractionMode = InteractionMode.MEETING
    opponent_strategy: OpponentStrategy = OpponentStrategy.ANALYTICAL
    ai_participants: int = Field(default=1, ge=1, le=3)
    event_intensity: int = Field(default=1, ge=0, le=2)
    decision_time_seconds: int = Field(default=90, ge=0, le=300)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)

    @field_validator("mode", mode="before")
    @classmethod
    def parse_mode(cls, value: InteractionMode | str) -> InteractionMode:
        return InteractionMode(value.strip()) if isinstance(value, str) else value

    @field_validator("opponent_strategy", mode="before")
    @classmethod
    def parse_strategy(cls, value: OpponentStrategy | str) -> OpponentStrategy:
        return OpponentStrategy(value.strip()) if isinstance(value, str) else value


class SessionConfiguration(BaseModel):
    """Immutable, user-scoped configuration captured by a training attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    topic: str = Field(min_length=3, max_length=120)
    context: str = Field(min_length=10, max_length=1200)
    participant_role: str = Field(min_length=2, max_length=100)
    opponent_role: str = Field(min_length=2, max_length=100)
    objective: str = Field(min_length=5, max_length=500)
    difficulty: SessionDifficulty = SessionDifficulty.MEDIUM
    tone: SessionTone = SessionTone.BUSINESSLIKE
    max_turns: int = Field(ge=6, le=20)
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)

    @field_validator(
        "topic", "context", "participant_role", "opponent_role", "objective", mode="before"
    )
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip()

    @field_validator("difficulty", mode="before")
    @classmethod
    def parse_difficulty(cls, value: SessionDifficulty | str) -> SessionDifficulty:
        if isinstance(value, SessionDifficulty):
            return value
        if isinstance(value, str):
            return SessionDifficulty(value.strip())
        return value

    @field_validator("tone", mode="before")
    @classmethod
    def parse_tone(cls, value: SessionTone | str) -> SessionTone:
        if isinstance(value, SessionTone):
            return value
        if isinstance(value, str):
            return SessionTone(value.strip())
        return value


class ScenarioTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    language: str
    title: str
    summary: str
    context: str
    participant_role: str
    opponent_role: str
    objective: str
    estimated_minutes: int = Field(ge=1)
    configurable: bool = False
    tone: str = "professional"
    difficulty: str = "medium"
    max_turns: int = Field(default=12, ge=6, le=20)
    methods: tuple[str, ...] = ()
    tasks: tuple[ScenarioTask, ...] = Field(min_length=1)
    industry: str = "Общее"
    negotiation_type: str = "procurement"
    theme: str = "Деловые переговоры"
    role_tags: tuple[str, ...] = ()
    source: Literal["curated", "custom"] = "curated"
    revision: int = Field(default=1, ge=1)


class ScenarioDraftRequest(BaseModel):
    """Allow-listed user input for a validated, deterministic scenario draft."""

    model_config = ConfigDict(extra="forbid")

    series_id: UUID | None = None
    template_id: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=5, max_length=120)
    situation: str = Field(min_length=30, max_length=1200)
    participant_role: str = Field(min_length=2, max_length=100)
    opponent_role: str = Field(min_length=2, max_length=100)
    objective: str = Field(min_length=10, max_length=500)
    industry: str = Field(min_length=2, max_length=80)
    theme: str = Field(min_length=2, max_length=80)
    difficulty: SessionDifficulty = SessionDifficulty.MEDIUM
    tone: SessionTone = SessionTone.BUSINESSLIKE
    estimated_minutes: int = Field(default=15, ge=5, le=60)
    max_turns: int = Field(default=12, ge=6, le=20)
    stakes_level: Literal["low", "standard", "high"] = "standard"

    @field_validator(
        "template_id", "title", "situation", "participant_role", "opponent_role",
        "objective", "industry", "theme", mode="before"
    )
    @classmethod
    def normalize_draft_text(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


class ScenarioBoundaryCheck(BaseModel):
    valid: Literal[True] = True
    checked_issues: int = Field(ge=1)
    overlapping_issues: int = Field(ge=0)
    no_overlap_issues: int = Field(ge=0)
    alternative_integrity: Literal[True] = True
    reservation_integrity: Literal[True] = True
    hidden_fields_exposed: Literal[False] = False


class ScenarioDraftResponse(BaseModel):
    id: UUID
    series_id: UUID
    version: int = Field(ge=1)
    scenario: Scenario
    validation: ScenarioBoundaryCheck
    created_at: datetime


class ScenarioDraftListResponse(BaseModel):
    drafts: list[ScenarioDraftResponse]


class ScenarioTextSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    situation: str = Field(min_length=10, max_length=1200)
    participant_role: str = Field(min_length=2, max_length=100)
    opponent_role: str = Field(min_length=2, max_length=100)
    objective: str = Field(min_length=5, max_length=500)


class ScenarioTextSuggestionResponse(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    situation: str = Field(min_length=10, max_length=1200)
    objective: str = Field(min_length=5, max_length=500)
    provider: Literal["gemini", "deterministic"]
    fallback: bool


class Message(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    role: str
    content: str = Field(min_length=1, max_length=4000)
    speaker_id: str | None = Field(default=None, max_length=64)
    speaker_label: str | None = Field(default=None, max_length=160)
    message_kind: Literal["dialogue", "event", "timeout"] = "dialogue"
    created_at: datetime = Field(default_factory=utc_now)


class VoiceObservations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pause_count: int = Field(default=0, ge=0, le=200)
    longest_pause_ms: int = Field(default=0, ge=0, le=120_000)
    speaking_rate_wpm: int = Field(default=0, ge=0, le=400)
    interruption_count: int = Field(default=0, ge=0, le=20)


class CreateVoiceRecordingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    audio_base64: str = Field(min_length=1, max_length=7_100_000)
    mime_type: str = Field(min_length=6, max_length=80, pattern=r"^audio/(webm|ogg|mp4|mpeg|wav)(;.*)?$")
    duration_ms: int = Field(ge=100, le=120_000)
    transcript: str = Field(min_length=1, max_length=4000)
    retention_policy: Literal["24_hours", "30_days"]
    consent: Literal[True]
    consent_version: Literal["voice-v1"] = "voice-v1"
    observations: VoiceObservations = Field(default_factory=VoiceObservations)

    @field_validator("transcript")
    @classmethod
    def voice_transcript_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Transcript must not be blank")
        return value


class VoiceRecordingResponse(BaseModel):
    id: UUID
    session_id: UUID
    message_id: UUID
    mime_type: str
    byte_size: int = Field(ge=1)
    duration_ms: int = Field(ge=100, le=120_000)
    transcript: str
    retention_policy: Literal["24_hours", "30_days"]
    observations: VoiceObservations
    audio_url: str
    expires_at: datetime
    created_at: datetime


class VoiceRecordingListResponse(BaseModel):
    recordings: list[VoiceRecordingResponse]


class SimulationOpponent(BaseModel):
    id: str = Field(pattern=r"^opponent_[1-3]$")
    label: str = Field(min_length=2, max_length=160)
    role: str = Field(min_length=2, max_length=160)
    strategy: OpponentStrategy
    memory: list[str] = Field(default_factory=list, max_length=8)


class SimulationEvent(BaseModel):
    id: str = Field(min_length=3, max_length=80)
    kind: Literal["budget", "deadline", "authority", "resource"]
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=800)
    trigger_turn: int = Field(ge=1, le=20)
    severity: int = Field(ge=1, le=3)
    zopa_preserved: Literal[True] = True


class SimulationDisclosure(BaseModel):
    id: str = Field(min_length=2, max_length=80)
    text: str = Field(min_length=3, max_length=1000)
    source_turn: int = Field(ge=1, le=20)


class SimulationHypothesis(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    text: str = Field(min_length=5, max_length=500)
    status: Literal["confirmed", "refuted", "insufficient"]
    explanation: str = Field(min_length=5, max_length=800)
    evidence_fact_id: str | None = Field(default=None, max_length=80)
    checked_at: datetime = Field(default_factory=utc_now)


class SimulationState(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    enabled: bool = False
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    mode: InteractionMode = InteractionMode.MEETING
    phase: NegotiationPhase = NegotiationPhase.PREPARATION
    server_time: datetime = Field(default_factory=utc_now)
    decision_time_seconds: int = Field(default=0, ge=0, le=300)
    deadline_at: datetime | None = None
    timed_out_decisions: int = Field(default=0, ge=0)
    pressure_score: int = Field(default=0, ge=0, le=100)
    event_schedule: list[SimulationEvent] = Field(default_factory=list, max_length=4)
    events: list[SimulationEvent] = Field(default_factory=list, max_length=4)
    disclosures: list[SimulationDisclosure] = Field(default_factory=list, max_length=20)
    hypotheses: list[SimulationHypothesis] = Field(default_factory=list, max_length=20)
    opponents: list[SimulationOpponent] = Field(default_factory=list, max_length=3)


class PublicSimulationOpponent(BaseModel):
    id: str
    label: str
    role: str
    strategy: OpponentStrategy


class SimulationSnapshot(BaseModel):
    enabled: bool
    seed: int
    mode: InteractionMode
    phase: NegotiationPhase
    decision_time_seconds: int
    deadline_at: datetime | None
    server_time: datetime
    timed_out_decisions: int
    pressure_score: int
    events: list[SimulationEvent]
    disclosures: list[SimulationDisclosure]
    hypotheses: list[SimulationHypothesis]
    opponents: list[PublicSimulationOpponent]


class CheckSimulationHypothesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=5, max_length=500)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


class CheckSimulationHypothesisResponse(BaseModel):
    hypothesis: SimulationHypothesis
    simulation: SimulationSnapshot


class NegotiationSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    series_id: UUID = Field(default_factory=uuid4)
    previous_session_id: UUID | None = None
    attempt_number: int = Field(default=1, ge=1)
    participant_user_id: UUID | None = None
    scenario_id: str
    scenario_version_id: str
    configuration: SessionConfiguration = Field(
        default_factory=lambda: SessionConfiguration(
            topic="Legacy training session",
            context="Legacy session context retained for compatibility.",
            participant_role="Participant",
            opponent_role="Opponent",
            objective="Complete the negotiation exercise.",
            max_turns=16,
        )
    )
    engine_state: NegotiationState
    simulation_state: SimulationState = Field(default_factory=SimulationState)
    reason_events: list[EngineEvent] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)

    scenario_id: str = Field(min_length=1)
    configuration: SessionConfiguration | None = None


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=320)
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=10, max_length=128)
    claim_session_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
            raise ValueError("invalid_email")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("password")
    @classmethod
    def password_has_letters_and_digits(cls, value: str) -> str:
        if not any(character.isalpha() for character in value) or not any(character.isdigit() for character in value):
            raise ValueError("password_requires_letters_and_digits")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    claim_session_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RecoverAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=320)
    recovery_code: str = Field(min_length=8, max_length=32)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("new_password")
    @classmethod
    def password_has_letters_and_digits(cls, value: str) -> str:
        if not any(character.isalpha() for character in value) or not any(character.isdigit() for character in value):
            raise ValueError("password_requires_letters_and_digits")
        return value


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)


class ClaimSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class AccountProfile(BaseModel):
    id: UUID
    email: str
    display_name: str
    roles: list[str]
    created_at: datetime


class AuthResponse(BaseModel):
    account: AccountProfile
    csrf_token: str
    recovery_code: str | None = None


class RecoveryResponse(BaseModel):
    recovery_code: str
    message: str


class AccountHistoryItem(BaseModel):
    session_id: UUID
    series_id: UUID
    attempt_number: int
    scenario_id: str
    topic: str
    status: SessionStatus
    outcome: NegotiationOutcome | None
    score: int | None = Field(default=None, ge=0, le=100)
    created_at: datetime
    completed_at: datetime | None


class AccountPeerReviewItem(BaseModel):
    assignment_id: UUID
    scenario_title: str
    status: str
    peer_score: int | None = Field(default=None, ge=0, le=100)
    reputation_points: int | None = Field(default=None, ge=0, le=100)
    assignment_kind: Literal["peer", "calibration"] = "peer"
    review_status: str = "draft"
    created_at: datetime
    submitted_at: datetime | None


class AccountHistoryResponse(BaseModel):
    negotiations: list[AccountHistoryItem]
    peer_reviews: list[AccountPeerReviewItem]


class LearningGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=2, max_length=40)
    target_score: int = Field(ge=40, le=100)
    weekly_sessions: int = Field(ge=1, le=7)


class LearningGoal(BaseModel):
    skill_id: str
    target_score: int = Field(ge=40, le=100)
    weekly_sessions: int = Field(ge=1, le=7)
    updated_at: datetime


class CompleteDrillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_rating: int = Field(ge=1, le=5)


CoachSkillId = Literal[
    "interests",
    "questions",
    "active_listening",
    "criteria",
    "meso",
    "exchanges",
    "batna",
    "commitments",
]


class PrebriefWorksheetRequest(BaseModel):
    """Private participant preparation; never part of the opponent prompt."""

    model_config = ConfigDict(extra="forbid")

    focus_skill: CoachSkillId = "interests"
    goal: str = Field(min_length=5, max_length=500)
    interests: list[str] = Field(default_factory=list, max_length=6)
    participant_batna: str = Field(min_length=5, max_length=500)
    participant_reservation: str = Field(min_length=5, max_length=500)
    planned_questions: list[str] = Field(default_factory=list, min_length=1, max_length=6)

    @field_validator("goal", "participant_batna", "participant_reservation", mode="before")
    @classmethod
    def normalize_prebrief_text(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("interests", "planned_questions", mode="before")
    @classmethod
    def normalize_prebrief_list(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            return value
        return [" ".join(item.split()) for item in value if isinstance(item, str) and item.strip()]


class PrebriefWorksheetResponse(PrebriefWorksheetRequest):
    id: UUID | None = None
    session_id: UUID
    saved: bool = False
    inherited_from_attempt: int | None = Field(default=None, ge=1)
    updated_at: datetime | None = None


class CoachBudget(BaseModel):
    used_tokens: int = Field(ge=0)
    remaining_tokens: int = Field(ge=0)
    used_calls: int = Field(ge=0)
    remaining_calls: int = Field(ge=0)


class CoachHintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: str = Field(default="", max_length=1200)
    skill_id: CoachSkillId | None = None
    mode: Literal["socratic"] = "socratic"

    @field_validator("draft", mode="before")
    @classmethod
    def normalize_hint_draft(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


class CoachHintResponse(BaseModel):
    question: str = Field(min_length=10, max_length=500)
    skill_id: CoachSkillId
    mode: Literal["socratic"] = "socratic"
    provider: Literal["gemini", "deterministic"]
    fallback: bool
    cached: bool = False
    role_aligned: Literal[True] = True
    official_outcome_unchanged: Literal[True] = True
    budget: CoachBudget


class CoachRewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    revised_text: str = Field(min_length=5, max_length=4000)

    @field_validator("revised_text", mode="before")
    @classmethod
    def normalize_rewrite(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


class CoachRewriteImpact(BaseModel):
    skill_id: CoachSkillId
    title: str
    effect: Literal["improved", "unchanged", "weakened"]
    explanation: str


class CoachRewriteResponse(BaseModel):
    official_message_id: UUID
    original_text: str
    revised_text: str
    possible_opponent_reply: str = Field(min_length=2, max_length=1000)
    analysis: str = Field(min_length=5, max_length=1200)
    impacts: list[CoachRewriteImpact] = Field(min_length=1)
    provider: Literal["gemini", "deterministic"]
    fallback: bool
    cached: bool = False
    role_aligned: Literal[True] = True
    official_transcript_changed: Literal[False] = False
    official_outcome_unchanged: Literal[True] = True
    budget: CoachBudget


class PersonalizedMiniDrill(BaseModel):
    id: str
    session_id: UUID
    skill_id: CoachSkillId
    title: str
    duration_minutes: int = Field(default=4, ge=1, le=10)
    prompt: str
    source_turn: int | None = Field(default=None, ge=1)
    source_quote: str | None = None
    instructions: list[str] = Field(min_length=1)
    success_checklist: list[str] = Field(min_length=1)
    suggested_template: str
    official_outcome_unchanged: Literal[True] = True


class CompleteAdaptiveDrillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=20, max_length=2000)

    @field_validator("answer", mode="before")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


class AdaptiveDrillCheck(BaseModel):
    title: str
    met: bool


class AdaptiveDrillFeedback(BaseModel):
    drill_id: str
    skill_id: CoachSkillId
    score: int = Field(ge=0, le=100)
    passed: bool
    feedback: str
    checks: list[AdaptiveDrillCheck] = Field(min_length=1)
    official_outcome_unchanged: Literal[True] = True


class AdaptiveCoachSummary(BaseModel):
    session_id: UUID
    focus_skill: CoachSkillId
    hint_count: int = Field(ge=0)
    rewrite_count: int = Field(ge=0)
    drill_completed: bool
    previous_skill_score: int | None = Field(default=None, ge=0, le=100)
    current_skill_score: int | None = Field(default=None, ge=0, le=100)
    skill_delta: int | None = Field(default=None, ge=-100, le=100)
    official_outcome_unchanged: Literal[True] = True
    budget: CoachBudget


class SkillProgress(BaseModel):
    id: str
    title: str
    description: str
    score: int | None = Field(default=None, ge=0, le=100)
    previous_score: int | None = Field(default=None, ge=0, le=100)
    delta: int | None = Field(default=None, ge=-100, le=100)
    attempts: int = Field(ge=0)
    status: Literal["new", "focus", "developing", "strong"]
    last_practiced_at: datetime | None = None
    next_due_at: datetime | None = None
    due: bool = False
    evidence_reason: str


class WeeklySkillProgress(BaseModel):
    period_start: date
    attempts: int = Field(ge=1)
    scores: dict[str, int]


class ScenarioSkillProgress(BaseModel):
    scenario_id: str
    scenario_title: str
    attempts: int = Field(ge=1)
    scores: dict[str, int]


class TrainerRecommendation(BaseModel):
    skill_id: str
    scenario_id: str
    scenario_title: str
    reason: str


class DrillDefinition(BaseModel):
    id: str
    skill_id: str
    title: str
    duration_minutes: int = Field(ge=1, le=15)
    prompt: str
    instructions: list[str] = Field(min_length=1)
    success_checklist: list[str] = Field(min_length=1)
    suggested_template: str


class LearningDashboardResponse(BaseModel):
    rubric_version: str | None
    evaluator_version: str | None = None
    comparable_sessions: int = Field(ge=0)
    excluded_incompatible_sessions: int = Field(ge=0)
    goal: LearningGoal | None
    skill_map: list[SkillProgress] = Field(min_length=8, max_length=8)
    weekly_progress: list[WeeklySkillProgress]
    scenario_progress: list[ScenarioSkillProgress]
    recommendation: TrainerRecommendation
    recommended_drill: DrillDefinition


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be blank")
        return value


class OpponentAudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID


class SessionResponse(BaseModel):
    id: UUID
    series_id: UUID
    previous_session_id: UUID | None
    attempt_number: int = Field(ge=1)
    scenario_id: str
    scenario_version_id: str
    configuration: SessionConfiguration
    status: SessionStatus
    outcome: NegotiationOutcome | None
    turn: int = Field(ge=0)
    trust: int = Field(ge=0, le=100)
    tension: int = Field(ge=0, le=100)
    progress: int = Field(ge=0, le=100)
    relationship: int = Field(ge=0, le=100)
    explanation: str
    messages: list[Message]
    simulation: SimulationSnapshot
    created_at: datetime
    completed_at: datetime | None


class GenerationMetadata(BaseModel):
    provider: Literal["gemini", "deterministic"]
    model: str | None = None
    fallback: bool = False
    reason: Literal["not_configured", "timeout", "provider_error", "invalid_response"] | None = None


class MessageExchangeResponse(BaseModel):
    participant_message: Message
    opponent_message: Message
    opponent_messages: list[Message] = Field(min_length=1, max_length=3)
    simulation_messages: list[Message] = Field(default_factory=list, max_length=3)
    session: SessionResponse
    generation: GenerationMetadata


class SimulationAssessment(BaseModel):
    participant_skill_score: int = Field(ge=0, le=100)
    environment_pressure_score: int = Field(ge=0, le=100)
    event_count: int = Field(ge=0)
    timed_out_decisions: int = Field(ge=0)
    ai_participants: int = Field(ge=1, le=3)
    phase_reached: NegotiationPhase
    mode: InteractionMode
    interpretation: str = Field(min_length=10)


class EvidenceItem(BaseModel):
    message_id: UUID
    turn: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=500)


class ScoreCriterion(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    score: int = Field(ge=0)
    max_score: int = Field(gt=0)
    explanation: str = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def score_does_not_exceed_maximum(self) -> "ScoreCriterion":
        if self.score > self.max_score:
            raise ValueError("Criterion score cannot exceed max_score")
        if self.score > 0 and not self.evidence:
            raise ValueError("A non-zero criterion score requires evidence")
        return self


class ScoreBlock(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    score: int = Field(ge=0)
    max_score: int = Field(gt=0)
    explanation: str = Field(min_length=1)
    criteria: list[ScoreCriterion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scores_and_evidence(self) -> "ScoreBlock":
        if self.score > self.max_score:
            raise ValueError("Block score cannot exceed max_score")
        criteria_score = sum(criterion.score for criterion in self.criteria)
        if criteria_score != self.score:
            raise ValueError("Block score must equal the sum of criterion scores")
        if self.score > 0 and not any(criterion.evidence for criterion in self.criteria):
            raise ValueError("A non-zero block score requires evidence")
        return self


class PenaltyItem(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    points: int = Field(lt=0)
    occurrences: int = Field(ge=0)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def occurrences_have_evidence(self) -> "PenaltyItem":
        if self.occurrences > 0 and not self.evidence:
            raise ValueError("A penalty with occurrences requires evidence")
        return self


class Finding(BaseModel):
    code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    points: int
    evidence: list[EvidenceItem] = Field(default_factory=list)


class Improvement(BaseModel):
    priority: int = Field(ge=1, le=3)
    title: str = Field(min_length=1)
    original_quote: str | None = Field(default=None, min_length=1, max_length=500)
    suggested_text: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    indicator_id: str = Field(min_length=1)


class TaskCheck(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: Literal["met", "not_met"]
    explanation: str = Field(min_length=1)
    accepted_value: str | None = Field(default=None, min_length=1)


class CoachingPoint(BaseModel):
    turn: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, min_length=1, max_length=500)
    problem: str = Field(min_length=1)
    better_approach: str = Field(min_length=1)
    suggested_text: str = Field(min_length=1)


class CoachingAnalysis(BaseModel):
    provider: Literal["gemini", "deterministic"]
    model: str | None = None
    fallback: bool = False
    reason: Literal["not_configured", "timeout", "provider_error", "invalid_response"] | None = None
    summary: str = Field(min_length=1)
    points: list[CoachingPoint] = Field(default_factory=list, max_length=3)


class TrajectoryPoint(BaseModel):
    turn: int = Field(ge=0)
    trust: int = Field(ge=0, le=100)
    tension: int = Field(ge=0, le=100)
    progress: int = Field(ge=0, le=100)
    relationship: int = Field(ge=0, le=100)


class OutcomeAnalysis(BaseModel):
    kind: Literal["agreement", "impasse", "walk_away", "incomplete"]
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    participant_utility: float | None = None
    batna_utility: float | None = None
    meets_batna: bool | None = None
    reservation_respected: bool | None = None
    accepted_terms: list[str] = Field(default_factory=list)


class MethodologyInfo(BaseModel):
    rubric_version: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    raw_score: int = Field(ge=0)
    penalty_points: int = Field(le=0)
    score_cap: int | None = Field(default=None, ge=0, le=100)
    disclaimer: str = Field(min_length=1)


class ReportResponse(BaseModel):
    session_id: UUID
    scenario_id: str
    scenario_version_id: str
    rubric_version: str
    evaluator_version: str = Field(min_length=1)
    status: SessionStatus
    score: int = Field(ge=0, le=100)
    level: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    outcome: OutcomeAnalysis
    blocks: list[ScoreBlock] = Field(min_length=1)
    penalties: list[PenaltyItem] = Field(default_factory=list)
    strengths: list[Finding] = Field(default_factory=list)
    improvements: list[Improvement] = Field(default_factory=list, max_length=3)
    task_checks: list[TaskCheck] = Field(min_length=1)
    coaching: CoachingAnalysis | None = None
    trajectory: list[TrajectoryPoint] = Field(min_length=1)
    methodology: MethodologyInfo
    next_step: str = Field(min_length=1)
    simulation: SimulationAssessment | None = None

    @model_validator(mode="after")
    def validate_report_totals(self) -> "ReportResponse":
        raw_score = sum(block.score for block in self.blocks)
        if raw_score != self.methodology.raw_score:
            raise ValueError("Methodology raw_score must equal the sum of block scores")

        penalty_points = sum(item.points * item.occurrences for item in self.penalties)
        if penalty_points != self.methodology.penalty_points:
            raise ValueError("Methodology penalty_points must equal the applied penalties")

        expected_score = max(0, min(100, raw_score + penalty_points))
        if self.methodology.score_cap is not None:
            expected_score = min(expected_score, self.methodology.score_cap)
        if self.score != expected_score:
            raise ValueError("Report score must match the documented scoring formula and cap")
        return self


class PeerReviewMessage(BaseModel):
    id: UUID
    sequence: int = Field(ge=1)
    role: Literal["participant", "opponent"]
    author_label: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=4000)


class PeerReviewCriterion(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    max_score: int = Field(gt=0, le=100)
    low_score_threshold: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def threshold_does_not_exceed_maximum(self) -> "PeerReviewCriterion":
        if self.low_score_threshold > self.max_score:
            raise ValueError("Low score threshold cannot exceed max_score")
        return self


class PeerReviewSla(BaseModel):
    blocking: Literal[False] = False
    target_hours: int = Field(default=24, ge=1, le=168)
    due_at: datetime = Field(default_factory=lambda: utc_now() + timedelta(hours=24))
    fallback: str = Field(
        default="Автоматический отчёт, retry и завершение обучения доступны без peer-review.",
        min_length=10,
    )


class PeerReviewAssignment(BaseModel):
    assignment_id: UUID
    scenario_id: str = Field(min_length=1)
    scenario_title: str = Field(min_length=1)
    anonymized: Literal[True] = True
    double_blind: Literal[True] = True
    participant_alias: str = Field(default="Участник A", min_length=3)
    reviewer_alias: str = Field(default="Рецензент R", min_length=3)
    language: Literal["ru", "en"] = "ru"
    difficulty: SessionDifficulty = SessionDifficulty.MEDIUM
    assignment_kind: Literal["peer", "calibration"] = "peer"
    review_round: int = Field(default=1, ge=1, le=2)
    matching_reasons: list[str] = Field(default_factory=list)
    sla: PeerReviewSla = Field(default_factory=PeerReviewSla)
    instructions: str = Field(min_length=1)
    messages: list[PeerReviewMessage] = Field(min_length=1)
    criteria: list[PeerReviewCriterion] = Field(min_length=1)


class PeerReviewItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    message_id: UUID
    comment: str = Field(min_length=12, max_length=1000)
    suggested_text: str | None = Field(default=None, min_length=8, max_length=1000)

    @field_validator("comment")
    @classmethod
    def comment_must_not_be_blank(cls, value: str) -> str:
        return value.strip()

    @field_validator("suggested_text")
    @classmethod
    def suggested_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class SubmitPeerReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_id: UUID
    items: list[PeerReviewItemInput] = Field(min_length=1)
    overall_comment: str = Field(min_length=12, max_length=1500)

    @field_validator("overall_comment")
    @classmethod
    def overall_comment_must_not_be_blank(cls, value: str) -> str:
        return value.strip()


class PeerReviewComparison(BaseModel):
    criterion_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    peer_score: int = Field(ge=0)
    automatic_score: int = Field(ge=0)
    max_score: int = Field(gt=0)
    difference: int


class ReviewerReputation(BaseModel):
    points: int = Field(ge=0, le=100)
    label: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    accuracy: int = Field(default=0, ge=0, le=100)
    evidence_quality: int = Field(default=0, ge=0, le=100)
    helpfulness: int = Field(default=0, ge=0, le=100)
    reviews_completed: int = Field(default=1, ge=1)
    strictness_neutral: Literal[True] = True


class PeerReviewResult(BaseModel):
    assignment_id: UUID
    peer_score: int = Field(ge=0, le=100)
    automatic_score: int = Field(ge=0, le=100)
    difference: int = Field(ge=-100, le=100)
    absolute_difference: int = Field(ge=0, le=100)
    comparison: list[PeerReviewComparison] = Field(min_length=1)
    reputation: ReviewerReputation
    official_score_unchanged: Literal[True] = True
    assignment_kind: Literal["peer", "calibration"] = "peer"
    review_round: int = Field(default=1, ge=1, le=2)
    review_status: Literal["accepted", "second_review_required", "resolved", "calibrated"] = "accepted"
    reviews_received: int = Field(default=1, ge=1, le=2)
    reviews_required: int = Field(default=1, ge=1, le=2)
    second_review_required: bool = False
    queue_non_blocking: Literal[True] = True
    feedback: str = Field(min_length=1)


class PeerReviewPublicItem(BaseModel):
    assignment_id: UUID
    reviewer_alias: str
    peer_score: int | None = Field(default=None, ge=0, le=100)
    review_round: int = Field(ge=1, le=2)
    status: str
    appeal_status: Literal["none", "pending", "resolved"] = "none"
    submitted_at: datetime | None = None


class PeerReviewSessionStatus(BaseModel):
    session_id: UUID
    status: Literal["waiting", "reviewed", "disputed", "re_reviewing", "resolved"]
    peer_review_blocking: Literal[False] = False
    official_score_unchanged: Literal[True] = True
    reviews_received: int = Field(ge=0, le=2)
    reviews_required: int = Field(ge=1, le=2)
    consensus_score: int | None = Field(default=None, ge=0, le=100)
    can_appeal: bool = False
    sla: PeerReviewSla
    reviews: list[PeerReviewPublicItem]


class PeerReviewAppealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=20, max_length=1500)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        return value.strip()


class PeerReviewAppealResponse(BaseModel):
    assignment_id: UUID
    appeal_status: Literal["pending", "resolved"]
    review_status: Literal["re_reviewing", "resolved"]
    message: str = Field(min_length=1)
    official_score_unchanged: Literal[True] = True
    peer_review_blocking: Literal[False] = False


class AttemptSnapshot(BaseModel):
    session_id: UUID
    attempt_number: int = Field(ge=1)
    rubric_version: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    level: str = Field(min_length=1)
    outcome_kind: Literal["agreement", "impasse", "walk_away", "incomplete"]
    outcome_label: str = Field(min_length=1)
    turns: int = Field(ge=0)
    tasks_met: int = Field(ge=0)
    tasks_total: int = Field(ge=1)
    completed_at: datetime


class AttemptBlockDelta(BaseModel):
    block_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    previous_score: int = Field(ge=0)
    current_score: int = Field(ge=0)
    max_score: int = Field(gt=0)
    delta: int


class AttemptTaskDelta(BaseModel):
    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    previous_status: Literal["met", "not_met"]
    current_status: Literal["met", "not_met"]
    change: Literal["improved", "regressed", "unchanged"]


class AttemptComparisonResponse(BaseModel):
    series_id: UUID
    scenario_id: str = Field(min_length=1)
    scenario_title: str = Field(min_length=1)
    previous: AttemptSnapshot
    current: AttemptSnapshot
    score_delta: int = Field(ge=-100, le=100)
    outcome_changed: bool
    block_deltas: list[AttemptBlockDelta] = Field(min_length=1)
    task_deltas: list[AttemptTaskDelta] = Field(min_length=1)
    improved_blocks: list[str] = Field(default_factory=list)
    regressed_blocks: list[str] = Field(default_factory=list)
    resolved_focus: list[str] = Field(default_factory=list)
    new_focus: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    next_step: str = Field(min_length=1)


class HistoricalAttemptComparisonResponse(BaseModel):
    """An explicit view of stored reports, without cross-version score deltas."""

    series_id: UUID
    scenario_id: str = Field(min_length=1)
    scenario_title: str = Field(min_length=1)
    previous: AttemptSnapshot
    current: AttemptSnapshot
    versions_match: bool
    summary: str = Field(min_length=1)
