"""sales_item_cost: snapshot of product cost on each sales line

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sales_order_items",
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
    )
    # Best available estimate for existing lines: the product's current cost price.
    op.execute(
        "UPDATE sales_order_items SET unit_cost = "
        "(SELECT p.cost_price FROM products p WHERE p.id = sales_order_items.product_id)"
    )


def downgrade() -> None:
    op.drop_column("sales_order_items", "unit_cost")
