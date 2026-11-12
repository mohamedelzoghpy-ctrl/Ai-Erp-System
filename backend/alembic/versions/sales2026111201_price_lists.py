"""Sales upgrades: price lists per customer + links.

Revision ID: sales2026111201
Revises: plat2026111201
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "sales2026111201"
down_revision = "plat2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_price_list_company_name"),
    )
    op.create_index("ix_price_lists_id", "price_lists", ["id"])
    op.create_index("ix_price_lists_company_id", "price_lists", ["company_id"])

    op.create_table(
        "price_list_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("price_list_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("price_list_id", "product_id", name="uq_price_list_item"),
    )
    op.create_index("ix_price_list_items_id", "price_list_items", ["id"])

    op.add_column("customers", sa.Column("price_list_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_customer_price_list", "customers", "price_lists", ["price_list_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_customer_price_list", "customers", type_="foreignkey")
    op.drop_column("customers", "price_list_id")
    op.drop_table("price_list_items")
    op.drop_table("price_lists")
