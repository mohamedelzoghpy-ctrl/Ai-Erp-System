"""Multi-currency: currencies table + FX snapshot columns on orders and payments.

Revision ID: curr2026111201
Revises: sales2026111201
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "curr2026111201"
down_revision = "sales2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "currencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("rate", sa.Numeric(14, 6), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_currency_company_code"),
    )
    op.create_index("ix_currencies_id", "currencies", ["id"])
    for table in ("sales_orders", "purchase_orders", "payments"):
        op.add_column(table, sa.Column("currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="SET NULL"), nullable=True))
        op.add_column(table, sa.Column("exchange_rate", sa.Numeric(14, 6), nullable=True))
        col = "foreign_amount" if table == "payments" else "foreign_total"
        op.add_column(table, sa.Column(col, sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "foreign_amount")
    op.drop_column("purchase_orders", "foreign_total")
    op.drop_column("sales_orders", "foreign_total")
    for table in ("sales_orders", "purchase_orders", "payments"):
        op.drop_column(table, "exchange_rate")
        op.drop_column(table, "currency_id")
    op.drop_table("currencies")
