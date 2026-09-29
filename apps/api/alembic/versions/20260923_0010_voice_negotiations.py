"""voice negotiations

Revision ID: 20260923_0010
Revises: 20260923_0009
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260923_0010"
down_revision: Union[str, None] = "20260923_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_recordings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("audio_data", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("pause_count", sa.Integer(), nullable=False),
        sa.Column("longest_pause_ms", sa.Integer(), nullable=False),
        sa.Column("speaking_rate_wpm", sa.Integer(), nullable=False),
        sa.Column("interruption_count", sa.Integer(), nullable=False),
        sa.Column("retention_policy", sa.String(length=20), nullable=False),
        sa.Column("consent_version", sa.String(length=20), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("duration_ms BETWEEN 100 AND 120000", name="ck_voice_duration"),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 5242880", name="ck_voice_byte_size"),
        sa.CheckConstraint("pause_count >= 0", name="ck_voice_pause_count"),
        sa.CheckConstraint("longest_pause_ms >= 0", name="ck_voice_longest_pause"),
        sa.CheckConstraint("speaking_rate_wpm BETWEEN 0 AND 400", name="ck_voice_speaking_rate"),
        sa.CheckConstraint("interruption_count >= 0", name="ck_voice_interruption_count"),
        sa.CheckConstraint("retention_policy IN ('24_hours', '30_days')", name="ck_voice_retention"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["negotiation_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_voice_recording_message"),
    )
    op.create_index("ix_voice_recordings_session_id", "voice_recordings", ["session_id"])
    op.create_index("ix_voice_recordings_message_id", "voice_recordings", ["message_id"])
    op.create_index("ix_voice_recordings_owner_user_id", "voice_recordings", ["owner_user_id"])
    op.create_index("ix_voice_recordings_expires_at", "voice_recordings", ["expires_at"])
    op.create_index("ix_voice_session_created", "voice_recordings", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_table("voice_recordings")
