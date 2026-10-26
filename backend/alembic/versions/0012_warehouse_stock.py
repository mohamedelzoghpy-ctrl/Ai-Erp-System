"""per-warehouse stock and warehouse transfers

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-26

`product_stock` holds the quantity of each product in each warehouse (Product.quantity stays the total).
Existing quantities are distributed from the stock-movement history: each movement already records its
warehouse, so a product that was received in warehouse A and sold from B ends up with the same split the
history implies. Whatever cannot be explained by history (negative per-warehouse sums, or a total that
differs from Product.quantity) is settled against the product's own warehouse, so the total is preserved.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def distribute(quantity, movement_sums, home):
    """Pure function: {warehouse_id: qty >= 0} whose values add up to `quantity`.

    movement_sums: {warehouse_id | None: sum of movement changes}; None = movement without a warehouse.
    home: the warehouse that absorbs any remainder.
    """
    if quantity <= 0:
        return {}
    per = {}
    for wid, change in movement_sums.items():
        key = home if wid is None else wid
        per[key] = per.get(key, 0) + change
    # a negative warehouse (sold where it was never received) is netted against the positive ones, largest first
    deficit = -sum(v for v in per.values() if v < 0)
    per = {k: v for k, v in per.items() if v > 0}
    for k in sorted(per, key=lambda k: -per[k]):
        take = min(per[k], deficit)
        per[k] -= take
        deficit -= take
    per = {k: v for k, v in per.items() if v > 0}
    total = sum(per.values())
    if total < quantity:
        per[home] = per.get(home, 0) + (quantity - total)
    elif total > quantity:
        extra = total - quantity
        for k in sorted(per, key=lambda k: -per[k]):
            take = min(per[k], extra)
            per[k] -= take
            extra -= take
        per = {k: v for k, v in per.items() if v > 0}
    return per


def upgrade() -> None:
    op.create_table(
        "product_stock",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_product_stock_quantity"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("product_id", "warehouse_id"),
    )
    op.create_index("ix_product_stock_warehouse_id", "product_stock", ["warehouse_id"])
    op.create_index("ix_product_stock_company_id", "product_stock", ["company_id"])

    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("from_warehouse_id", sa.Integer(), nullable=False),
        sa.Column("to_warehouse_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("from_warehouse_id <> to_warehouse_id", name="ck_transfer_distinct_warehouses"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["to_warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_transfers_id", "stock_transfers", ["id"])
    op.create_index("ix_stock_transfers_company_id", "stock_transfers", ["company_id"])
    op.create_index("ix_stock_transfers_from_warehouse_id", "stock_transfers", ["from_warehouse_id"])
    op.create_index("ix_stock_transfers_to_warehouse_id", "stock_transfers", ["to_warehouse_id"])

    op.create_table(
        "stock_transfer_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("transfer_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_transfer_item_quantity"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["transfer_id"], ["stock_transfers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_transfer_items_id", "stock_transfer_items", ["id"])
    op.create_index("ix_stock_transfer_items_company_id", "stock_transfer_items", ["company_id"])
    op.create_index("ix_stock_transfer_items_product_id", "stock_transfer_items", ["product_id"])
    op.create_index("ix_stock_transfer_items_transfer_id", "stock_transfer_items", ["transfer_id"])

    # ---- backfill from the movement history
    bind = op.get_bind()
    sums = {}
    for pid, wid, total in bind.execute(sa.text("SELECT product_id, warehouse_id, SUM(change) FROM stock_movements GROUP BY product_id, warehouse_id")):
        sums.setdefault(pid, {})[wid] = int(total)
    warehouses = {}  # company_id -> oldest warehouse id
    for wid, cid in bind.execute(sa.text("SELECT id, company_id FROM warehouses ORDER BY id")):
        warehouses.setdefault(cid, wid)
    products = bind.execute(sa.text("SELECT id, company_id, warehouse_id, quantity FROM products WHERE quantity > 0")).fetchall()
    for pid, cid, home, quantity in products:
        home = home if home is not None else warehouses.get(cid)
        if home is None:  # stock in a company with no warehouse at all: give the company one so the quantity has a place
            branch = bind.execute(sa.text("SELECT id FROM branches WHERE company_id = :c ORDER BY id LIMIT 1"), {"c": cid}).scalar()
            if branch is None:
                raise RuntimeError(f"Product {pid} has stock but company {cid} has no branch/warehouse to hold it")
            home = bind.execute(
                sa.text("INSERT INTO warehouses (company_id, branch_id, name, code, is_active) VALUES (:c, :b, 'المخزن الرئيسي', 'MAIN', true) RETURNING id"),
                {"c": cid, "b": branch},
            ).scalar()
            warehouses[cid] = home
        for wid, qty in distribute(quantity, sums.get(pid, {}), home).items():
            bind.execute(
                sa.text("INSERT INTO product_stock (product_id, warehouse_id, company_id, quantity) VALUES (:p, :w, :c, :q)"),
                {"p": pid, "w": wid, "c": cid, "q": qty},
            )


def downgrade() -> None:
    for table in ("stock_transfer_items", "stock_transfers", "product_stock"):
        op.drop_table(table)
