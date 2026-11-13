"""المرحلة 2 من خطة التصنيع: MRP التنفيذي — ربط أمر التصنيع بأمر البيع + سريان إصدارات BOM.

Revision ID: m22026111402
Revises: qcm2026111303
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "m22026111402"
down_revision = "qcm2026111303"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_orders",
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_production_orders_sales_order_id", "production_orders", ["sales_order_id"])
    op.add_column("boms", sa.Column("valid_from", sa.Date(), nullable=True))
    op.add_column("boms", sa.Column("valid_to", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("boms", "valid_to")
    op.drop_column("boms", "valid_from")
    op.drop_index("ix_production_orders_sales_order_id", table_name="production_orders")
    op.drop_column("production_orders", "sales_order_id")
