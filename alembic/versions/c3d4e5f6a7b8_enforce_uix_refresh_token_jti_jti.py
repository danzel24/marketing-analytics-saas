"""Enforce UNIQUE on refresh_token_jti.jti (replay protection).

Legacy DBs may have created ``refresh_token_jti`` without a unique index on ``jti``,
so duplicate inserts succeeded and ``try_consume_refresh_jti`` returned True on reuse.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "refresh_token_jti" not in insp.get_table_names():
        return

    # Remove duplicate jti rows (keep smallest id) so UNIQUE index can be created.
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            text(
                """
                DELETE FROM refresh_token_jti
                WHERE id NOT IN (
                    SELECT MIN(id) FROM refresh_token_jti GROUP BY jti
                )
                """
            )
        )
    else:
        # PostgreSQL / others: same idea
        op.execute(
            text(
                """
                DELETE FROM refresh_token_jti a
                USING refresh_token_jti b
                WHERE a.jti = b.jti AND a.id > b.id
                """
            )
        )

    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uix_refresh_token_jti_jti ON refresh_token_jti (jti)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uix_refresh_token_jti_jti"))
