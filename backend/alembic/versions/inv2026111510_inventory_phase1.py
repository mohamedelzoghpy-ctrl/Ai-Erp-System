"""مخازن م1: وحدات قياس (حزمة) + باركودات متعددة + أسباب التسويات + توقيع الحركة.

Revision ID: inv2026111510
Revises: c2_2026111409
Create Date: 2026-11-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "inv2026111510"
down_revision = "c2_2026111409"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("pack_qty", sa.Numeric(12, 3), nullable=False, server_default="1"))
    op.add_column("products", sa.Column("pack_name", sa.String(30), nullable=True))
    op.create_table(
        "product_barcodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("pack_qty", sa.Numeric(12, 3), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "barcode", name="uq_product_barcode"),
    )
    op.create_index("ix_product_barcodes_product_id", "product_barcodes", ["product_id"])
    op.create_index("ix_product_barcodes_company_id", "product_barcodes", ["company_id"])
    op.create_table(
        "adjustment_reasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.UniqueConstraint("company_id", "name", name="uq_adjustment_reason"),
    )
    op.add_column("stock_movements", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("stock_movements", sa.Column("reason_note", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_movements", "reason_note")
    op.drop_column("stock_movements", "user_id")
    op.drop_table("adjustment_reasons")
    op.drop_table("product_barcodes")
    op.drop_column("products", "pack_name")
    op.drop_column("products", "pack_qty")
