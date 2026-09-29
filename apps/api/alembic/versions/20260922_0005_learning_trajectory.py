"""Add personal learning goals and spaced drill completions.

Revision ID: 20260922_0005
Revises: 20260922_0004
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0005"
down_revision = "20260922_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_preferences",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("goal_skill_id", sa.String(40), nullable=False),
        sa.Column("target_score", sa.Integer(), nullable=False),
        sa.Column("weekly_sessions", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target_score BETWEEN 40 AND 100", name="ck_learning_goal_target"),
        sa.CheckConstraint("weekly_sessions BETWEEN 1 AND 7", name="ck_learning_goal_weekly_sessions"),
    )
    op.create_table(
        "skill_drill_completions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.String(40), nullable=False),
        sa.Column("drill_id", sa.String(80), nullable=False),
        sa.Column("self_rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("self_rating BETWEEN 1 AND 5", name="ck_drill_completion_rating"),
    )
    op.create_index("ix_skill_drill_completions_user_id", "skill_drill_completions", ["user_id"])
    op.create_index("ix_drill_completions_user_skill", "skill_drill_completions", ["user_id", "skill_id"])


def downgrade() -> None:
    op.drop_table("skill_drill_completions")
    op.drop_table("learning_preferences")
