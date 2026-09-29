"""Add private prebriefs and cached adaptive-coach artifacts.

Revision ID: 20260922_0007
Revises: 20260922_0006
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0007"
down_revision = "20260922_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adaptive_prebriefs",
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("focus_skill", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_adaptive_prebriefs_user_id", "adaptive_prebriefs", ["user_id"])

    op.create_table(
        "adaptive_coach_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("estimated_tokens >= 0", name="ck_adaptive_coach_tokens_nonnegative"),
        sa.UniqueConstraint("session_id", "kind", "fingerprint", name="uq_adaptive_coach_cache"),
    )
    op.create_index("ix_adaptive_coach_artifacts_session_id", "adaptive_coach_artifacts", ["session_id"])
    op.create_index("ix_adaptive_coach_artifacts_user_id", "adaptive_coach_artifacts", ["user_id"])
    op.create_index("ix_adaptive_coach_session_kind", "adaptive_coach_artifacts", ["session_id", "kind"])


def downgrade() -> None:
    op.drop_table("adaptive_coach_artifacts")
    op.drop_table("adaptive_prebriefs")
