"""Add versioned user scenario drafts.

Revision ID: 20260922_0006
Revises: 20260922_0005
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0006"
down_revision = "20260922_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_draft_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("series_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("public_projection", sa.JSON(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_number >= 1", name="ck_scenario_draft_version_positive"),
        sa.UniqueConstraint("series_id", "version_number", name="uq_scenario_draft_series_version"),
        sa.UniqueConstraint("scenario_id", name="uq_scenario_draft_scenario_id"),
    )
    op.create_index("ix_scenario_draft_versions_series_id", "scenario_draft_versions", ["series_id"])
    op.create_index("ix_scenario_draft_versions_user_id", "scenario_draft_versions", ["user_id"])
    op.create_index("ix_scenario_drafts_user_series", "scenario_draft_versions", ["user_id", "series_id"])


def downgrade() -> None:
    op.drop_table("scenario_draft_versions")
