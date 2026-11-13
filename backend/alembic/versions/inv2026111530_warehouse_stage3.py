"""مخازن م3: حجز المخزون (ATP) + التحليلات (دوران/راكد/ABC) + حد أقصى ذكي لكل مخزن.

- stock_reservations: حجز صريح لمسودة أمر بيع (يُخصم من «متاح للبيع»)
- product_stock.max_level: حد أقصى لكل مخزن يقود اقتراحات الشراء (طلب حتى الحد الأقصى)

Revision ID: inv2026111530
Revises: inv2026111520
Create Date: 2026-11-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "inv2026111530"
down_revision = "inv2026111520"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("sales_order_id", "product_id", name="uq_reservation_order_product"),
    )
    op.create_index("ix_stock_reservations_company_id", "stock_reservations", ["company_id"])
    op.create_index("ix_stock_reservations_product_id", "stock_reservations", ["product_id"])
    op.add_column("product_stock", sa.Column("max_level", sa.Numeric(12, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("product_stock", "max_level")
    op.drop_index("ix_stock_reservations_product_id", table_name="stock_reservations")
    op.drop_index("ix_stock_reservations_company_id", table_name="stock_reservations")
    op.drop_table("stock_reservations")
