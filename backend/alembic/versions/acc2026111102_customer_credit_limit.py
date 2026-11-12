"""Customer credit limits.

Revision ID: acc2026111102
Revises: acc2026111101
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "acc2026111102"
down_revision = "acc2026111101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "credit_limit")
