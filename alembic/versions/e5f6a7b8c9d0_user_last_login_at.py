"""Add user.last_login_at (password login tracking).

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-04-21

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    # Idempotent: baseline migration creates user with last_login_at when run on fresh DBs.
    cols = {c["name"] for c in insp.get_columns("user")}
    if "last_login_at" not in cols:
        op.add_column("user", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    idx_names = {idx["name"] for idx in insp.get_indexes("user")}
    if "ix_user_last_login_at" not in idx_names:
        op.create_index(op.f("ix_user_last_login_at"), "user", ["last_login_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_last_login_at"), table_name="user")
    op.drop_column("user", "last_login_at")
