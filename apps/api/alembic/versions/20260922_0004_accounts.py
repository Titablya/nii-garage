"""Add password-backed accounts and opaque server sessions.

Revision ID: 20260922_0004
Revises: 20260920_0003
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


revision = "20260922_0004"
down_revision = "20260920_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text()))
    op.add_column("users", sa.Column("recovery_code_hash", sa.String(64)))
    op.create_table(
        "account_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_sessions_user_id", "account_sessions", ["user_id"])
    op.create_index("ix_account_sessions_token_hash", "account_sessions", ["token_hash"])
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])
    roles = sa.table(
        "roles",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        roles,
        [
            {"id": "participant", "name": "Участник", "description": "Проходит переговорные тренировки", "created_at": now},
            {"id": "reviewer", "name": "Рецензент", "description": "Проверяет анонимизированные диалоги", "created_at": now},
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_roles WHERE role_id IN ('participant', 'reviewer')")
    op.execute("DELETE FROM roles WHERE id IN ('participant', 'reviewer')")
    op.drop_table("account_sessions")
    op.drop_column("users", "recovery_code_hash")
    op.drop_column("users", "password_hash")
