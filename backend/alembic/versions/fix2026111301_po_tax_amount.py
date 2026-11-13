"""Purchase orders: persist discount_amount / tax_amount so the receive endpoint
posts the VAT-input split correctly and debits inventory net of VAT (parity with
the immediate-receipt path).

Revision ID: fix2026111301
Revises: plat2026111207
Create Date: 2026-11-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "fix2026111301"
down_revision = "plat2026111207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("purchase_orders", "tax_amount")
    op.drop_column("purchase_orders", "discount_amount")
