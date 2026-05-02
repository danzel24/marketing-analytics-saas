"""Add Lead OS tables ``lead`` and ``leadinteraction`` (internal admin outreach).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-02

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_name", sa.String(length=512), nullable=False),
        sa.Column("website", sa.String(length=512), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_linkedin", sa.String(length=512), nullable=True),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("signal_strength", sa.String(length=32), nullable=False),
        sa.Column("decision_level", sa.String(length=64), nullable=True),
        sa.Column("source_of_truth", sa.String(length=64), nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_follow_up_at", sa.Date(), nullable=True),
        sa.Column("next_action", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lead_company_name"), "lead", ["company_name"], unique=False)
    op.create_index(op.f("ix_lead_contact_email"), "lead", ["contact_email"], unique=False)
    op.create_index(op.f("ix_lead_status"), "lead", ["status"], unique=False)
    op.create_index(op.f("ix_lead_signal_strength"), "lead", ["signal_strength"], unique=False)
    op.create_index(op.f("ix_lead_last_contacted_at"), "lead", ["last_contacted_at"], unique=False)
    op.create_index(op.f("ix_lead_next_follow_up_at"), "lead", ["next_follow_up_at"], unique=False)
    op.create_index(op.f("ix_lead_created_at"), "lead", ["created_at"], unique=False)
    op.create_index(op.f("ix_lead_updated_at"), "lead", ["updated_at"], unique=False)

    op.create_table(
        "leadinteraction",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("message_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_leadinteraction_lead_id"), "leadinteraction", ["lead_id"], unique=False
    )
    op.create_index(
        op.f("ix_leadinteraction_created_at"), "leadinteraction", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_leadinteraction_created_at"), table_name="leadinteraction")
    op.drop_index(op.f("ix_leadinteraction_lead_id"), table_name="leadinteraction")
    op.drop_table("leadinteraction")

    op.drop_index(op.f("ix_lead_updated_at"), table_name="lead")
    op.drop_index(op.f("ix_lead_created_at"), table_name="lead")
    op.drop_index(op.f("ix_lead_next_follow_up_at"), table_name="lead")
    op.drop_index(op.f("ix_lead_last_contacted_at"), table_name="lead")
    op.drop_index(op.f("ix_lead_signal_strength"), table_name="lead")
    op.drop_index(op.f("ix_lead_status"), table_name="lead")
    op.drop_index(op.f("ix_lead_contact_email"), table_name="lead")
    op.drop_index(op.f("ix_lead_company_name"), table_name="lead")
    op.drop_table("lead")
