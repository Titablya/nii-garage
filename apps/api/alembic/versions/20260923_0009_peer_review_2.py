"""Upgrade peer review to the double-blind School 21 v2 workflow.

Revision ID: 20260923_0009
Revises: 20260922_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0009"
down_revision: str | None = "20260922_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("peer_reviews", sa.Column("assignment_kind", sa.String(24), nullable=False, server_default="peer"))
    op.add_column("peer_reviews", sa.Column("language", sa.String(8), nullable=False, server_default="ru"))
    op.add_column("peer_reviews", sa.Column("difficulty", sa.String(20), nullable=False, server_default="medium"))
    op.add_column("peer_reviews", sa.Column("review_round", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("peer_reviews", sa.Column("subject_user_id", sa.String(36), nullable=True))
    op.add_column("peer_reviews", sa.Column("participant_alias", sa.String(80), nullable=False, server_default="Участник A"))
    op.add_column("peer_reviews", sa.Column("reviewer_alias", sa.String(80), nullable=False, server_default="Рецензент R"))
    op.add_column("peer_reviews", sa.Column("appeal_status", sa.String(20), nullable=False, server_default="none"))
    op.add_column("peer_reviews", sa.Column("appeal_reason", sa.Text(), nullable=True))
    op.add_column("peer_reviews", sa.Column("appeal_resolution", sa.Text(), nullable=True))
    op.add_column("peer_reviews", sa.Column("appealed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("peer_reviews", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_peer_reviews_subject_user", "peer_reviews", "users", ["subject_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_peer_reviews_subject_user_id", "peer_reviews", ["subject_user_id"])
    op.create_index("ix_peer_reviews_matching", "peer_reviews", ["language", "difficulty", "status"])


def downgrade() -> None:
    op.drop_index("ix_peer_reviews_matching", table_name="peer_reviews")
    op.drop_index("ix_peer_reviews_subject_user_id", table_name="peer_reviews")
    op.drop_constraint("fk_peer_reviews_subject_user", "peer_reviews", type_="foreignkey")
    for column in (
        "resolved_at",
        "appealed_at",
        "appeal_resolution",
        "appeal_reason",
        "appeal_status",
        "reviewer_alias",
        "participant_alias",
        "subject_user_id",
        "review_round",
        "difficulty",
        "language",
        "assignment_kind",
    ):
        op.drop_column("peer_reviews", column)
