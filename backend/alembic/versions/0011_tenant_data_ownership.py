"""tenant ownership for business data

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "warehouses",
    "suppliers",
    "products",
    "customers",
    "purchase_orders",
    "purchase_order_items",
    "sales_orders",
    "sales_order_items",
    "stock_movements",
    "payments",
    "audit_logs",
    "sales_returns",
    "sales_return_items",
    "purchase_returns",
    "purchase_return_items",
    "shifts",
    "stocktakes",
    "stocktake_lines",
)


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("company_id", sa.Integer(), nullable=True))

    op.execute(
        "UPDATE warehouses SET company_id = "
        "(SELECT company_id FROM branches WHERE branches.id = warehouses.branch_id)"
    )
    for table in ("suppliers", "customers"):
        op.execute(
            f"UPDATE {table} SET company_id = (SELECT id FROM companies WHERE code = 'default')"
        )
    op.execute(
        "UPDATE products SET company_id = COALESCE("
        "(SELECT company_id FROM warehouses WHERE warehouses.id = products.warehouse_id), "
        "(SELECT company_id FROM suppliers WHERE suppliers.id = products.supplier_id), "
        "(SELECT id FROM companies WHERE code = 'default'))"
    )
    op.execute(
        "UPDATE purchase_orders SET company_id = "
        "(SELECT company_id FROM warehouses WHERE warehouses.id = purchase_orders.warehouse_id)"
    )
    op.execute(
        "UPDATE purchase_order_items SET company_id = "
        "(SELECT company_id FROM purchase_orders WHERE purchase_orders.id = purchase_order_items.order_id)"
    )
    op.execute(
        "UPDATE sales_orders SET company_id = "
        "(SELECT company_id FROM warehouses WHERE warehouses.id = sales_orders.warehouse_id)"
    )
    op.execute(
        "UPDATE sales_order_items SET company_id = "
        "(SELECT company_id FROM sales_orders WHERE sales_orders.id = sales_order_items.order_id)"
    )
    op.execute(
        "UPDATE stock_movements SET company_id = "
        "(SELECT company_id FROM products WHERE products.id = stock_movements.product_id)"
    )
    op.execute(
        "UPDATE payments SET company_id = COALESCE("
        "(SELECT company_id FROM customers WHERE customers.id = payments.customer_id), "
        "(SELECT company_id FROM suppliers WHERE suppliers.id = payments.supplier_id))"
    )
    op.execute(
        "UPDATE audit_logs SET company_id = COALESCE("
        "(SELECT company_id FROM user_company_memberships "
        "WHERE user_company_memberships.user_id = audit_logs.user_id), "
        "(SELECT id FROM companies WHERE code = 'default'))"
    )
    op.execute(
        "UPDATE sales_returns SET company_id = "
        "(SELECT company_id FROM sales_orders WHERE sales_orders.id = sales_returns.order_id)"
    )
    op.execute(
        "UPDATE sales_return_items SET company_id = "
        "(SELECT company_id FROM sales_returns WHERE sales_returns.id = sales_return_items.return_id)"
    )
    op.execute(
        "UPDATE purchase_returns SET company_id = "
        "(SELECT company_id FROM purchase_orders WHERE purchase_orders.id = purchase_returns.order_id)"
    )
    op.execute(
        "UPDATE purchase_return_items SET company_id = "
        "(SELECT company_id FROM purchase_returns WHERE purchase_returns.id = purchase_return_items.return_id)"
    )
    op.execute(
        "UPDATE shifts SET company_id = COALESCE("
        "(SELECT company_id FROM user_company_memberships "
        "WHERE user_company_memberships.user_id = shifts.user_id), "
        "(SELECT id FROM companies WHERE code = 'default'))"
    )
    op.execute(
        "UPDATE stocktakes SET company_id = COALESCE("
        "(SELECT company_id FROM warehouses WHERE warehouses.id = stocktakes.warehouse_id), "
        "(SELECT company_id FROM user_company_memberships "
        "WHERE user_company_memberships.user_id = stocktakes.created_by), "
        "(SELECT id FROM companies WHERE code = 'default'))"
    )
    op.execute(
        "UPDATE stocktake_lines SET company_id = "
        "(SELECT company_id FROM stocktakes WHERE stocktakes.id = stocktake_lines.stocktake_id)"
    )

    for table in TENANT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
            batch_op.create_foreign_key(
                f"fk_{table}_company_id_companies",
                "companies",
                ["company_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch_op.create_index(f"ix_{table}_company_id", ["company_id"], unique=False)

    for table, column in (("warehouses", "name"), ("warehouses", "code"), ("products", "sku")):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)

    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.create_unique_constraint("uq_warehouse_company_name", ["company_id", "name"])
        batch_op.create_unique_constraint("uq_warehouse_company_code", ["company_id", "code"])
    with op.batch_alter_table("products") as batch_op:
        batch_op.create_unique_constraint("uq_product_company_sku", ["company_id", "sku"])


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint("uq_product_company_sku", type_="unique")
    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.drop_constraint("uq_warehouse_company_code", type_="unique")
        batch_op.drop_constraint("uq_warehouse_company_name", type_="unique")
    for table, column in (("warehouses", "name"), ("warehouses", "code"), ("products", "sku")):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=True)

    for table in reversed(TENANT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_company_id")
            batch_op.drop_constraint(f"fk_{table}_company_id_companies", type_="foreignkey")
            batch_op.drop_column("company_id")
