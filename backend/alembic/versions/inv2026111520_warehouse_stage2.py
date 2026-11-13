"""مخازن م2: استلام جزئي لأمر الشراء + بوابة فحص جودة الاستلام + التحويلات بمرحلة نقل.

- purchase_order_items.received_quantity: المُستلم فعليًا من كل بند (استلامات متعددة)
- products.qc_required: مادة حساسة تستقبل لوطها «بانتظار الفحص» مع بوابة PO_QC_GATE
- stock_lots.qc_status: حالة فحص اللوط (passed/pending/failed) — يمنع صرف المعلّق
- stock_transfers.booked_value + stock_transfer_items.received_quantity + warehouses.is_transit:
  مرحلة النقل (مخزن عابر) مع قيد «مخزون تحت النقل 1103»

Revision ID: inv2026111520
Revises: inv2026111510
Create Date: 2026-11-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "inv2026111520"
down_revision = "inv2026111510"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_order_items", sa.Column("received_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"))
    op.add_column("products", sa.Column("qc_required", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("stock_lots", sa.Column("qc_status", sa.String(20), nullable=False, server_default="passed"))
    op.create_index("ix_stock_lots_qc_status", "stock_lots", ["qc_status"])
    op.add_column("stock_transfers", sa.Column("booked_value", sa.Numeric(14, 2), nullable=True))
    op.add_column("stock_transfer_items", sa.Column("received_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"))
    op.add_column("warehouses", sa.Column("is_transit", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("warehouses", "is_transit")
    op.drop_column("stock_transfer_items", "received_quantity")
    op.drop_column("stock_transfers", "booked_value")
    op.drop_index("ix_stock_lots_qc_status", table_name="stock_lots")
    op.drop_column("stock_lots", "qc_status")
    op.drop_column("products", "qc_required")
    op.drop_column("purchase_order_items", "received_quantity")
