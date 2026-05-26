"""Add email_verified to user and emailverificationtoken table.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-26

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # --- email_verified column on user -----------------------------------
    user_cols = {c["name"] for c in inspector.get_columns("user")}
    if "email_verified" not in user_cols:
        op.add_column(
            "user",
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                # server_default=true so existing rows are auto-verified;
                # new rows have email_verified=False set explicitly by the app.
                server_default=sa.text("true"),
            ),
        )
        op.create_index(
            op.f("ix_user_email_verified"), "user", ["email_verified"], unique=False
        )

    # --- emailverificationtoken table ------------------------------------
    if "emailverificationtoken" not in existing_tables:
        op.create_table(
            "emailverificationtoken",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "used",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_emailverificationtoken_user_id"),
            "emailverificationtoken",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_emailverificationtoken_token"),
            "emailverificationtoken",
            ["token"],
            unique=True,
        )
        op.create_index(
            op.f("ix_emailverificationtoken_expires_at"),
            "emailverificationtoken",
            ["expires_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_emailverificationtoken_used"),
            "emailverificationtoken",
            ["used"],
            unique=False,
        )
        op.create_index(
            op.f("ix_emailverificationtoken_created_at"),
            "emailverificationtoken",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_emailverificationtoken_created_at"),
        table_name="emailverificationtoken",
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_used"), table_name="emailverificationtoken"
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_expires_at"),
        table_name="emailverificationtoken",
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_token"), table_name="emailverificationtoken"
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_user_id"), table_name="emailverificationtoken"
    )
    op.drop_table("emailverificationtoken")
    op.drop_index(op.f("ix_user_email_verified"), table_name="user")
    op.drop_column("user", "email_verified")
