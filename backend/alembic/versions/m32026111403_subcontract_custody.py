"""المرحلة 3: عهدة التصنيع لدى الغير — جدول تتبع الخامات المسلّمة للمُصنّعين.

Revision ID: m32026111403
Revises: m22026111402
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "m32026111403"
down_revision = "m22026111402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subcontract_custodies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subcontractor_id", sa.Integer(), sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qty_sent", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("qty_returned", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("order_id", "product_id", name="uq_subcontract_custody"),
    )
    op.create_index("ix_subcontract_custodies_id", "subcontract_custodies", ["id"])
    op.create_index("ix_subcontract_custodies_company_id", "subcontract_custodies", ["company_id"])
    op.create_index("ix_subcontract_custodies_order_id", "subcontract_custodies", ["order_id"])
    op.create_index("ix_subcontract_custodies_subcontractor_id", "subcontract_custodies", ["subcontractor_id"])
    op.create_index("ix_subcontract_custodies_product_id", "subcontract_custodies", ["product_id"])


def downgrade() -> None:
    op.drop_table("subcontract_custodies")
