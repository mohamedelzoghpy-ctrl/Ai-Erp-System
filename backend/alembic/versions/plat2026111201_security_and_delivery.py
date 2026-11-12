"""Platform security + partial deliveries + maker-checker setting.

Revision ID: plat2026111201
Revises: eta2026111102
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111201"
down_revision = "eta2026111102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("companies", sa.Column("je_approval_threshold", sa.Numeric(14, 2), nullable=True))
    op.add_column("sales_order_items", sa.Column("delivered_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("sales_order_items", "delivered_quantity")
    op.drop_column("companies", "je_approval_threshold")
    op.drop_column("users", "token_version")
