"""مخازن م4: الجرد المحترف (أعمي + بوابة اعتماد الفروق) + الأرقام التسلسلية.

- stocktakes.mode: open (الجرد العادي) | blind (العد بلا رصيد النظام)
- products.serial_tracking: تتبع أرقام تسلسلية للأصناف الحساسة (موبايلات/أجهزة)
- products.warranty_months: مدة الضمان بالشهور (لحساب نهاية الضمان في التقرير)
- product_serials: سجل الأرقام — حالتها (متاح/مباع) ومرجع الاستلام والبيع

Revision ID: inv2026111540
Revises: inv2026111530
Create Date: 2026-11-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "inv2026111540"
down_revision = "inv2026111530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocktakes", sa.Column("mode", sa.String(10), nullable=False, server_default="open"))
    op.add_column("products", sa.Column("serial_tracking", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("products", sa.Column("warranty_months", sa.Integer(), nullable=True))
    op.create_table(
        "product_serials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("serial", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_stock"),  # in_stock | sold
        sa.Column("source_ref", sa.String(80), nullable=True),   # PO-x / يدوي
        sa.Column("sale_ref", sa.String(80), nullable=True),     # SO-x
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("company_id", "product_id", "serial", name="uq_serial_per_product"),
    )
    op.create_index("ix_product_serials_company_id", "product_serials", ["company_id"])
    op.create_index("ix_product_serials_product_id", "product_serials", ["product_id"])


def downgrade() -> None:
    op.drop_table("product_serials")
    op.drop_column("products", "warranty_months")
    op.drop_column("products", "serial_tracking")
    op.drop_column("stocktakes", "mode")
