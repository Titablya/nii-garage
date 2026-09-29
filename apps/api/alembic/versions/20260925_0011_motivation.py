"""Opt-in motivation and server-registered challenge attempts.

Revision ID: 20260925_0011
Revises: 20260923_0010
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260925_0011"
down_revision: Union[str, None] = "20260923_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "motivation_teams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("invite_code", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_motivation_teams_invite_code", "motivation_teams", ["invite_code"], unique=True)
    op.create_table(
        "motivation_preferences",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("team_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("motivation_teams.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_motivation_preferences_team_id", "motivation_preferences", ["team_id"])
    op.create_table(
        "motivation_challenge_entries",
        sa.Column("session_id", sa.String(36), sa.ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("period_key", sa.String(24), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("motivation_teams.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('daily', 'weekly')", name="ck_motivation_challenge_kind"),
        sa.UniqueConstraint("user_id", "kind", "period_key", name="uq_motivation_challenge_user_period"),
    )
    op.create_index("ix_motivation_challenge_entries_user_id", "motivation_challenge_entries", ["user_id"])
    op.create_index("ix_motivation_challenge_entries_team_id", "motivation_challenge_entries", ["team_id"])
    op.create_index("ix_motivation_challenge_period", "motivation_challenge_entries", ["kind", "period_key"])


def downgrade() -> None:
    op.drop_table("motivation_challenge_entries")
    op.drop_table("motivation_preferences")
    op.drop_table("motivation_teams")
