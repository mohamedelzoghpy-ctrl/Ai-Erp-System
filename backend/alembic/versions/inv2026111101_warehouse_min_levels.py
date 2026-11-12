"""Per-warehouse minimum stock levels.

Revision ID: inv2026111101
Revises: acc2026111102
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "inv2026111101"
down_revision = "acc2026111102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_stock", sa.Column("min_level", sa.Numeric(12, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("product_stock", "min_level")
