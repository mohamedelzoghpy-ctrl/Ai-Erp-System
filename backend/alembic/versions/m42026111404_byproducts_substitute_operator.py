"""المرحلة 4: منتجات ثانوية + خامة بديلة + مشغّل العمليات/الدفعات.

Revision ID: m42026111404
Revises: m32026111403
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "m42026111404"
down_revision = "m32026111403"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_byproducts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_production_byproducts_id", "production_byproducts", ["id"])
    op.create_index("ix_production_byproducts_company_id", "production_byproducts", ["company_id"])
    op.create_index("ix_production_byproducts_order_id", "production_byproducts", ["order_id"])
    op.create_index("ix_production_byproducts_batch_id", "production_byproducts", ["batch_id"])
    op.create_index("ix_production_byproducts_product_id", "production_byproducts", ["product_id"])
    op.add_column("bom_items", sa.Column("substitute_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True))
    op.add_column("production_order_operations", sa.Column("operator_name", sa.String(length=100), nullable=True))
    op.add_column("production_order_operations", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("production_batches", sa.Column("operator_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("production_batches", "operator_name")
    op.drop_column("production_order_operations", "started_at")
    op.drop_column("production_order_operations", "operator_name")
    op.drop_column("bom_items", "substitute_product_id")
    op.drop_table("production_byproducts")
