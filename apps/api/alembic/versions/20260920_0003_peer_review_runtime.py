"""Persist peer-review assignment and result payloads.

Revision ID: 20260920_0003
Revises: 20260918_0002
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260920_0003"
down_revision = "20260918_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("peer_reviews", sa.Column("assignment_payload", sa.JSON()))
    op.add_column("peer_reviews", sa.Column("automatic_report", sa.JSON()))
    op.add_column("peer_reviews", sa.Column("result_payload", sa.JSON()))
    op.add_column("peer_review_items", sa.Column("suggested_text", sa.Text()))


def downgrade() -> None:
    op.drop_column("peer_review_items", "suggested_text")
    op.drop_column("peer_reviews", "result_payload")
    op.drop_column("peer_reviews", "automatic_report")
    op.drop_column("peer_reviews", "assignment_payload")
