"""sales_orders.safe_id (اسم الخزينة على مسودة/فاتورة المبيعات)

Revision ID: a1b2c3d4e5f6
Revises: f482c19a7d31
Create Date: 2026-11-04 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'f482c19a7d31'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_orders", sa.Column("safe_id", sa.Integer(), sa.ForeignKey("safes.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("sales_orders", "safe_id")
