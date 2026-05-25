"""Add passwordresettoken table for forgot-password flow.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-25

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())

    # Idempotent: baseline migration creates this table when run on fresh DBs.
    # server_default="false" is valid for both PostgreSQL BOOLEAN and SQLite INTEGER.
    if "passwordresettoken" not in existing:
        op.create_table(
            "passwordresettoken",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_passwordresettoken_user_id"), "passwordresettoken", ["user_id"], unique=False
        )
        op.create_index(
            op.f("ix_passwordresettoken_token"), "passwordresettoken", ["token"], unique=True
        )
        op.create_index(
            op.f("ix_passwordresettoken_expires_at"), "passwordresettoken", ["expires_at"], unique=False
        )
        op.create_index(
            op.f("ix_passwordresettoken_used"), "passwordresettoken", ["used"], unique=False
        )
        op.create_index(
            op.f("ix_passwordresettoken_created_at"), "passwordresettoken", ["created_at"], unique=False
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_passwordresettoken_created_at"), table_name="passwordresettoken")
    op.drop_index(op.f("ix_passwordresettoken_used"), table_name="passwordresettoken")
    op.drop_index(op.f("ix_passwordresettoken_expires_at"), table_name="passwordresettoken")
    op.drop_index(op.f("ix_passwordresettoken_token"), table_name="passwordresettoken")
    op.drop_index(op.f("ix_passwordresettoken_user_id"), table_name="passwordresettoken")
    op.drop_table("passwordresettoken")
