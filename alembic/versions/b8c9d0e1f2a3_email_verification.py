"""Add email_verified to user and create emailverificationtoken table.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-26

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in inspect(bind).get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    # Add email_verified to user table (existing rows default to True — already verified)
    if _table_exists("user") and not _column_exists("user", "email_verified"):
        op.add_column(
            "user",
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        op.create_index("ix_user_email_verified", "user", ["email_verified"])

    # Create emailverificationtoken table
    if not _table_exists("emailverificationtoken"):
        op.create_table(
            "emailverificationtoken",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_emailverificationtoken_expires_at", "emailverificationtoken", ["expires_at"])
        op.create_index("ix_emailverificationtoken_token", "emailverificationtoken", ["token"], unique=True)
        op.create_index("ix_emailverificationtoken_used", "emailverificationtoken", ["used"])
        op.create_index("ix_emailverificationtoken_user_id", "emailverificationtoken", ["user_id"])
        op.create_index("ix_emailverificationtoken_created_at", "emailverificationtoken", ["created_at"])


def downgrade() -> None:
    if _table_exists("emailverificationtoken"):
        op.drop_index("ix_emailverificationtoken_created_at", table_name="emailverificationtoken")
        op.drop_index("ix_emailverificationtoken_user_id", table_name="emailverificationtoken")
        op.drop_index("ix_emailverificationtoken_used", table_name="emailverificationtoken")
        op.drop_index("ix_emailverificationtoken_token", table_name="emailverificationtoken")
        op.drop_index("ix_emailverificationtoken_expires_at", table_name="emailverificationtoken")
        op.drop_table("emailverificationtoken")

    if _table_exists("user") and _column_exists("user", "email_verified"):
        op.drop_index("ix_user_email_verified", table_name="user")
        op.drop_column("user", "email_verified")
