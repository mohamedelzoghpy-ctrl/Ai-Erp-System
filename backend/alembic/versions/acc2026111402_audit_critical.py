"""إصلاحات حرجة متبقية من تدقيق 2026-11-14 (2 + متوسطة مرتبطة):

- مرتجعات المبيعات/المشتريات: حقول الضريبة وحصة الخصم — عكس ضريبة 2130/1145
  وحصة الطرف تُحسب من المستند الأصلي بدل تجاهل الضريبة كليًا
- client_ref للمزامنة أوفلاين: فهرس فريد جزئي يمنع تكرار الأوامر على المزامنات المتزامنة
  (الترحيلة السابقة plat2026111204 أنشأت فهرسًا عاديًا فقط)

Revision ID: acc2026111402
Revises: acc2026111401
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "acc2026111402"
down_revision = "acc2026111401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # البيانات الحية تحققت يدويًا: صفر client_ref مكرر قبل الفهارس الفريدة
    op.add_column("sales_returns", sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("sales_returns", sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("sales_returns", sa.Column("discount_share", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchase_returns", sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("purchase_returns", sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("purchase_returns", sa.Column("discount_share", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.create_index(
        "uq_sales_order_client_ref", "sales_orders",
        ["company_id", "rep_id", "client_ref"], unique=True,
        postgresql_where=sa.text("client_ref IS NOT NULL"),
        sqlite_where=sa.text("client_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_crm_activity_client_ref", "crm_activities",
        ["company_id", "client_ref"], unique=True,
        postgresql_where=sa.text("client_ref IS NOT NULL"),
        sqlite_where=sa.text("client_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_crm_activity_client_ref", table_name="crm_activities")
    op.drop_index("uq_sales_order_client_ref", table_name="sales_orders")
    op.drop_column("purchase_returns", "discount_share")
    op.drop_column("purchase_returns", "tax_amount")
    op.drop_column("purchase_returns", "tax_rate")
    op.drop_column("sales_returns", "discount_share")
    op.drop_column("sales_returns", "tax_amount")
    op.drop_column("sales_returns", "tax_rate")
