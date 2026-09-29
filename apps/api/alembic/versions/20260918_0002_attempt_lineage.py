"""Add immutable attempt lineage.

Revision ID: 20260918_0002
Revises: 20260917_0001
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260918_0002"
down_revision = "20260917_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("negotiation_sessions", sa.Column("series_id", sa.String(36), nullable=True))
    op.add_column(
        "negotiation_sessions",
        sa.Column("previous_session_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "negotiation_sessions",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute("UPDATE negotiation_sessions SET series_id = id WHERE series_id IS NULL")
    # Batch operations preserve compatibility with local SQLite while using
    # regular ALTER statements on PostgreSQL.
    with op.batch_alter_table("negotiation_sessions") as batch_op:
        batch_op.alter_column("series_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_session_previous_attempt",
            "negotiation_sessions",
            ["previous_session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_session_attempt_number_positive",
            "attempt_number >= 1",
        )
        batch_op.create_unique_constraint(
            "uq_session_series_attempt",
            ["series_id", "attempt_number"],
        )
    op.create_index(
        "ix_negotiation_sessions_series_id",
        "negotiation_sessions",
        ["series_id"],
    )
    op.create_index(
        "ix_negotiation_sessions_previous_session_id",
        "negotiation_sessions",
        ["previous_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_negotiation_sessions_previous_session_id", table_name="negotiation_sessions")
    op.drop_index("ix_negotiation_sessions_series_id", table_name="negotiation_sessions")
    with op.batch_alter_table("negotiation_sessions") as batch_op:
        batch_op.drop_constraint("uq_session_series_attempt", type_="unique")
        batch_op.drop_constraint("ck_session_attempt_number_positive", type_="check")
        batch_op.drop_constraint("fk_session_previous_attempt", type_="foreignkey")
    op.drop_column("negotiation_sessions", "attempt_number")
    op.drop_column("negotiation_sessions", "previous_session_id")
    op.drop_column("negotiation_sessions", "series_id")
