"""Persist the advanced negotiation simulation state.

Revision ID: 20260922_0008
Revises: 20260922_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0008"
down_revision: str | None = "20260922_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("negotiation_sessions", sa.Column("simulation_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("negotiation_sessions", "simulation_snapshot")
