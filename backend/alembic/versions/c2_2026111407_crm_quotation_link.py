"""CRM م2: ربط أوامر البيع (وعروض الأسعار) بالقائد الذي ولّدها.

Revision ID: c2_2026111407
Revises: c2_2026111406
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c2_2026111407"
down_revision = "c2_2026111406"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sales_orders",
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_sales_orders_lead_id", "sales_orders", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_sales_orders_lead_id", table_name="sales_orders")
    op.drop_column("sales_orders", "lead_id")
