"""الكميات العشرية: تحويل كل أعمدة الكميات من Integer إلى Numeric(12,3)

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-11-08

يدعم وحدات كسرية (0.5 كجم مثلًا) في المخزون وأوامر الشراء/البيع والمرتجعات
والتحويلات والجرد والتصنيع. القيم الحالية أعداد صحيحة فالتحويل آمن (int → numeric ضمنيًا).
"""
from alembic import op
import sqlalchemy as sa

revision = "k0l1m2n3o4p5"
down_revision = "j9k0l1m2n3o4"
branch_labels = None
depends_on = None

# (table, column, existing_server_default)
_QTY_COLUMNS = [
    ("products", "quantity", "0"),
    ("purchase_order_items", "quantity", None),
    ("sales_order_items", "quantity", None),
    ("stock_movements", "change", None),
    ("sales_return_items", "quantity", None),
    ("purchase_return_items", "quantity", None),
    ("product_stock", "quantity", "0"),
    ("stock_transfer_items", "quantity", None),
    ("stocktake_lines", "system_qty", None),
    ("stocktake_lines", "counted_qty", None),
    ("production_orders", "qty_planned", None),
    ("production_orders", "qty_produced", "0"),
    ("production_orders", "qty_scrapped", "0"),
    ("production_consumptions", "qty", None),
    ("production_batches", "qty", None),
]


def upgrade() -> None:
    for table, column, server_default in _QTY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(12, 3),
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default=sa.text(f"'{server_default}'") if server_default else None,
        )


def downgrade() -> None:
    for table, column, server_default in _QTY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Integer(),
            existing_type=sa.Numeric(12, 3),
            existing_nullable=False,
            postgresql_using=f"{column}::integer",
            existing_server_default=sa.text(f"'{server_default}'") if server_default else None,
        )
