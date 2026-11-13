"""Mobile sync: idempotent client reference on sales orders.

Revision ID: plat2026111204
Revises: plat2026111203
Create Date: 2026-11-12 00:00:00.000000

عمود sales_orders.client_ref: معرف فريد يولده التطبيق لكل أوردر أوفلاين —
يضمن عدم تكرار الأوردر عند إعادة المحاولة/المزامنة أكثر من مرة.
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111204"
down_revision = "plat2026111203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_orders", sa.Column("client_ref", sa.String(length=64), nullable=True))
    op.create_index("ix_sales_orders_client_ref", "sales_orders", ["client_ref"])


def downgrade() -> None:
    op.drop_index("ix_sales_orders_client_ref", table_name="sales_orders")
    op.drop_column("sales_orders", "client_ref")
