"""Portable SQLAlchemy 2.x persistence model for the negotiation platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, TimestampMixin, utc_now


def uuid_string() -> str:
    return str(uuid4())


JsonValue = dict[str, Any] | list[Any]


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    recovery_code_hash: Mapped[str | None] = mapped_column(String(64))
    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    account_sessions: Mapped[list["AccountSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class LearningPreference(TimestampMixin, Base):
    __tablename__ = "learning_preferences"
    __table_args__ = (
        CheckConstraint("target_score BETWEEN 40 AND 100", name="ck_learning_goal_target"),
        CheckConstraint("weekly_sessions BETWEEN 1 AND 7", name="ck_learning_goal_weekly_sessions"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    goal_skill_id: Mapped[str] = mapped_column(String(40), nullable=False)
    target_score: Mapped[int] = mapped_column(Integer, nullable=False)
    weekly_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=2)


class SkillDrillCompletion(CreatedAtMixin, Base):
    __tablename__ = "skill_drill_completions"
    __table_args__ = (
        CheckConstraint("self_rating BETWEEN 1 AND 5", name="ck_drill_completion_rating"),
        Index("ix_drill_completions_user_skill", "user_id", "skill_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(40), nullable=False)
    drill_id: Mapped[str] = mapped_column(String(80), nullable=False)
    self_rating: Mapped[int] = mapped_column(Integer, nullable=False)


class MotivationTeam(CreatedAtMixin, Base):
    __tablename__ = "motivation_teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)


class MotivationPreference(TimestampMixin, Base):
    __tablename__ = "motivation_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    team_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    team_id: Mapped[str | None] = mapped_column(ForeignKey("motivation_teams.id", ondelete="SET NULL"), index=True)


class MotivationChallengeEntry(CreatedAtMixin, Base):
    __tablename__ = "motivation_challenge_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "period_key", name="uq_motivation_challenge_user_period"),
        CheckConstraint("kind IN ('daily', 'weekly')", name="ck_motivation_challenge_kind"),
        Index("ix_motivation_challenge_period", "kind", "period_key"),
    )

    session_id: Mapped[str] = mapped_column(ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    period_key: Mapped[str] = mapped_column(String(24), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("motivation_teams.id", ondelete="SET NULL"), index=True)


class AdaptivePrebrief(TimestampMixin, Base):
    __tablename__ = "adaptive_prebriefs"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    focus_skill: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)


class AdaptiveCoachArtifact(CreatedAtMixin, Base):
    __tablename__ = "adaptive_coach_artifacts"
    __table_args__ = (
        UniqueConstraint("session_id", "kind", "fingerprint", name="uq_adaptive_coach_cache"),
        CheckConstraint("estimated_tokens >= 0", name="ck_adaptive_coach_tokens_nonnegative"),
        Index("ix_adaptive_coach_session_kind", "session_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    response_payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScenarioDraftVersion(CreatedAtMixin, Base):
    __tablename__ = "scenario_draft_versions"
    __table_args__ = (
        UniqueConstraint("series_id", "version_number", name="uq_scenario_draft_series_version"),
        UniqueConstraint("scenario_id", name="uq_scenario_draft_scenario_id"),
        CheckConstraint("version_number >= 1", name="ck_scenario_draft_version_positive"),
        Index("ix_scenario_drafts_user_series", "user_id", "series_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    series_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    definition: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    public_projection: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    validation: Mapped[JsonValue] = mapped_column(JSON, nullable=False)


class AccountSession(CreatedAtMixin, Base):
    __tablename__ = "account_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    user: Mapped[User] = relationship(back_populates="account_sessions")


class Role(CreatedAtMixin, Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    users: Mapped[list["UserRole"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class UserRole(CreatedAtMixin, Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="users")


class Scenario(TimestampMixin, Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    versions: Mapped[list["ScenarioVersion"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class ScenarioVersion(CreatedAtMixin, Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (
        UniqueConstraint("scenario_id", "version_number", name="uq_scenario_version_number"),
        CheckConstraint("version_number >= 1", name="ck_scenario_version_number_positive"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_scenario_version_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    definition: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    # Set when published; services will later enforce that this snapshot is immutable.
    content_hash: Mapped[str | None] = mapped_column(String(128))
    immutable_snapshot: Mapped[JsonValue | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    scenario: Mapped[Scenario] = relationship(back_populates="versions")
    sessions: Mapped[list["NegotiationSession"]] = relationship(back_populates="scenario_version")


class NegotiationSession(CreatedAtMixin, Base):
    __tablename__ = "negotiation_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'abandoned')", name="ck_session_status"),
        CheckConstraint("status != 'completed' OR completed_at IS NOT NULL", name="ck_completed_session_timestamp"),
        CheckConstraint("attempt_number >= 1", name="ck_session_attempt_number_positive"),
        UniqueConstraint("series_id", "attempt_number", name="uq_session_series_attempt"),
        Index("ix_sessions_participant_status", "participant_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    series_id: Mapped[str] = mapped_column(String(36), nullable=False, default=uuid_string, index=True)
    previous_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("negotiation_sessions.id", ondelete="SET NULL"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scenario_version_id: Mapped[str] = mapped_column(ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    participant_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Immutable audit material captured at completion by a later service layer.
    scenario_snapshot: Mapped[JsonValue | None] = mapped_column(JSON)
    simulation_snapshot: Mapped[JsonValue | None] = mapped_column(JSON)
    transcript_hash: Mapped[str | None] = mapped_column(String(128))
    final_state_hash: Mapped[str | None] = mapped_column(String(128))
    immutable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="sessions")
    messages: Mapped[list["MessageRecord"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    state_events: Mapped[list["SessionStateEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class MessageRecord(CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number", name="uq_message_session_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    author_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[JsonValue | None] = mapped_column("metadata", JSON)
    session: Mapped[NegotiationSession] = relationship(back_populates="messages")


class VoiceRecording(CreatedAtMixin, Base):
    __tablename__ = "voice_recordings"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_voice_recording_message"),
        CheckConstraint("duration_ms BETWEEN 100 AND 120000", name="ck_voice_duration"),
        CheckConstraint("byte_size BETWEEN 1 AND 5242880", name="ck_voice_byte_size"),
        CheckConstraint("pause_count >= 0", name="ck_voice_pause_count"),
        CheckConstraint("longest_pause_ms >= 0", name="ck_voice_longest_pause"),
        CheckConstraint("speaking_rate_wpm BETWEEN 0 AND 400", name="ck_voice_speaking_rate"),
        CheckConstraint("interruption_count >= 0", name="ck_voice_interruption_count"),
        CheckConstraint("retention_policy IN ('24_hours', '30_days')", name="ck_voice_retention"),
        Index("ix_voice_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    audio_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    pause_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_pause_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    speaking_rate_wpm: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interruption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retention_policy: Mapped[str] = mapped_column(String(20), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SessionStateEvent(CreatedAtMixin, Base):
    __tablename__ = "session_state_events"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number", name="uq_state_event_session_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    session: Mapped[NegotiationSession] = relationship(back_populates="state_events")


class AgentRun(CreatedAtMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    triggering_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(150))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    output_payload: Mapped[JsonValue | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[str | None] = mapped_column(String(100), index=True)


class EvaluationRun(CreatedAtMixin, Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[JsonValue | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="evaluation_run", cascade="all, delete-orphan")


class EvidenceItem(CreatedAtMixin, Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    criterion_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[JsonValue | None] = mapped_column(JSON)
    evaluation_run: Mapped[EvaluationRun] = relationship(back_populates="evidence_items")


class PeerReview(CreatedAtMixin, Base):
    __tablename__ = "peer_reviews"
    __table_args__ = (UniqueConstraint("session_id", "reviewer_user_id", name="uq_peer_review_session_reviewer"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    assignment_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="peer")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    review_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    participant_alias: Mapped[str] = mapped_column(String(80), nullable=False, default="Участник A")
    reviewer_alias: Mapped[str] = mapped_column(String(80), nullable=False, default="Рецензент R")
    assignment_payload: Mapped[JsonValue | None] = mapped_column(JSON)
    automatic_report: Mapped[JsonValue | None] = mapped_column(JSON)
    result_payload: Mapped[JsonValue | None] = mapped_column(JSON)
    overall_comment: Mapped[str | None] = mapped_column(Text)
    appeal_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    appeal_reason: Mapped[str | None] = mapped_column(Text)
    appeal_resolution: Mapped[str | None] = mapped_column(Text)
    appealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list["PeerReviewItem"]] = relationship(back_populates="peer_review", cascade="all, delete-orphan")


class PeerReviewItem(CreatedAtMixin, Base):
    __tablename__ = "peer_review_items"
    __table_args__ = (UniqueConstraint("peer_review_id", "criterion_code", name="uq_peer_review_item_criterion"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    peer_review_id: Mapped[str] = mapped_column(ForeignKey("peer_reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_code: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    suggested_text: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    peer_review: Mapped[PeerReview] = relationship(back_populates="items")
