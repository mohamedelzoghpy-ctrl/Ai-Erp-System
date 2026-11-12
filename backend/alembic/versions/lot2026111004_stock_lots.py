"""Raw material lot tracking: stock_lots + consumption_lots (FIFO traceability)

Revision ID: lot2026111004
Revises: lic2026111003
Create Date: 2026-11-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "lot2026111004"
down_revision = "lic2026111003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # لوطات الخامات لكل (منتج × مخزن × كود لوط)
    op.create_table(
        "stock_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("lot_code", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("reference", sa.String(length=80), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("qty_received", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("qty_remaining", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "product_id", "warehouse_id", "lot_code", name="uq_stock_lot_code"),
    )
    op.create_index("ix_stock_lots_id", "stock_lots", ["id"])
    op.create_index("ix_stock_lots_company_id", "stock_lots", ["company_id"])
    op.create_index("ix_stock_lots_product_id", "stock_lots", ["product_id"])
    op.create_index("ix_stock_lots_warehouse_id", "stock_lots", ["warehouse_id"])

    # تخصيص صرف الخامات على اللوطات
    op.create_table(
        "consumption_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("component_id", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(12, 3), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["production_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["component_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["lot_id"], ["stock_lots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "component_id", "lot_id", name="uq_consumption_lot"),
    )
    op.create_index("ix_consumption_lots_id", "consumption_lots", ["id"])
    op.create_index("ix_consumption_lots_company_id", "consumption_lots", ["company_id"])
    op.create_index("ix_consumption_lots_order_id", "consumption_lots", ["order_id"])
    op.create_index("ix_consumption_lots_component_id", "consumption_lots", ["component_id"])
    op.create_index("ix_consumption_lots_lot_id", "consumption_lots", ["lot_id"])


def downgrade() -> None:
    op.drop_table("consumption_lots")
    op.drop_table("stock_lots")
