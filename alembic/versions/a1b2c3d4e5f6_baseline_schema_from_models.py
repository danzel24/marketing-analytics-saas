"""Baseline: create any missing tables from SQLModel metadata (idempotent).

Existing SQLite databases that already used ``create_all`` simply no-op for existing tables.
New environments get a full schema. Legacy partial indexes are added with IF NOT EXISTS.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-30

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlmodel import SQLModel

    import app.models  # noqa: F401 — register metadata

    bind = op.get_bind()
    insp = inspect(bind)
    names = set(insp.get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in names:
            table.create(bind=bind)
            names.add(table.name)

    # Legacy compatibility indexes (may already exist from runtime PRAGMA migrations).
    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uix_campaign_metric_campaign_date "
            'ON campaignmetric ("campaign_id", "metric_date")'
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_campaign_client_name ON campaign (client_id, name)"
        )
    )


def downgrade() -> None:
    raise NotImplementedError("Intentionally unsupported: forward-only baseline.")
