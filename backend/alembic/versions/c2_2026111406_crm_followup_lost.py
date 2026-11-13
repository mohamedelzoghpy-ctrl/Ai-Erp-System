"""CRM م1: موعد المتابعة القادم + سبب الفقد.

Revision ID: c2_2026111406
Revises: m52026111405
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c2_2026111406"
down_revision = "m52026111405"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_leads", sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_leads", sa.Column("lost_reason", sa.String(length=200), nullable=True))
    op.create_index("ix_crm_leads_next_follow_up_at", "crm_leads", ["next_follow_up_at"])


def downgrade() -> None:
    op.drop_index("ix_crm_leads_next_follow_up_at", table_name="crm_leads")
    op.drop_column("crm_leads", "lost_reason")
    op.drop_column("crm_leads", "next_follow_up_at")
