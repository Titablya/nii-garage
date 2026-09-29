"""Initial persistence schema for negotiation sessions.

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260917_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "roles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scenarios_slug", "scenarios", ["slug"])
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.String(64), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scenario_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scenario_id", sa.String(36), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(128)),
        sa.Column("immutable_snapshot", sa.JSON()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scenario_id", "version_number", name="uq_scenario_version_number"),
        sa.CheckConstraint("version_number >= 1", name="ck_scenario_version_number_positive"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_scenario_version_status"),
    )
    op.create_index("ix_scenario_versions_scenario_id", "scenario_versions", ["scenario_id"])
    op.create_index("ix_scenario_versions_status", "scenario_versions", ["status"])
    op.create_table(
        "negotiation_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scenario_version_id", sa.String(36), sa.ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("participant_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("scenario_snapshot", sa.JSON()),
        sa.Column("transcript_hash", sa.String(128)),
        sa.Column("final_state_hash", sa.String(128)),
        sa.Column("immutable_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'completed', 'abandoned')", name="ck_session_status"),
        sa.CheckConstraint("status != 'completed' OR completed_at IS NOT NULL", name="ck_completed_session_timestamp"),
    )
    op.create_index("ix_negotiation_sessions_scenario_version_id", "negotiation_sessions", ["scenario_version_id"])
    op.create_index("ix_negotiation_sessions_participant_user_id", "negotiation_sessions", ["participant_user_id"])
    op.create_index("ix_negotiation_sessions_status", "negotiation_sessions", ["status"])
    op.create_index("ix_sessions_participant_status", "negotiation_sessions", ["participant_user_id", "status"])
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("author_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_message_session_sequence"),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_table(
        "session_state_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_state_event_session_sequence"),
    )
    op.create_index("ix_session_state_events_session_id", "session_state_events", ["session_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("triggering_message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(150)),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("trace_id", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_index("ix_agent_runs_triggering_message_id", "agent_runs", ["triggering_message_id"])
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evaluator_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("result", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evaluation_runs_session_id", "evaluation_runs", ["session_id"])
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evaluation_run_id", sa.String(36), sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("criterion_code", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_items_evaluation_run_id", "evidence_items", ["evaluation_run_id"])
    op.create_index("ix_evidence_items_message_id", "evidence_items", ["message_id"])
    op.create_index("ix_evidence_items_criterion_code", "evidence_items", ["criterion_code"])
    op.create_table(
        "peer_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("overall_comment", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "reviewer_user_id", name="uq_peer_review_session_reviewer"),
    )
    op.create_index("ix_peer_reviews_session_id", "peer_reviews", ["session_id"])
    op.create_index("ix_peer_reviews_reviewer_user_id", "peer_reviews", ["reviewer_user_id"])
    op.create_table(
        "peer_review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("peer_review_id", sa.String(36), sa.ForeignKey("peer_reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion_code", sa.String(100), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("comment", sa.Text()),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("peer_review_id", "criterion_code", name="uq_peer_review_item_criterion"),
    )
    op.create_index("ix_peer_review_items_peer_review_id", "peer_review_items", ["peer_review_id"])
    op.create_index("ix_peer_review_items_message_id", "peer_review_items", ["message_id"])


def downgrade() -> None:
    for table in ("peer_review_items", "peer_reviews", "evidence_items", "evaluation_runs", "agent_runs", "session_state_events", "messages", "negotiation_sessions", "scenario_versions", "user_roles", "scenarios", "roles", "users"):
        op.drop_table(table)
