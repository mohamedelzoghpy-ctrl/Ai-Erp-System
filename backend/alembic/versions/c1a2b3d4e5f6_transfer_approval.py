"""stock transfer approval workflow (status, approved_by, approved_at, rejection_reason)

Revision ID: c1a2b3d4e5f6
Revises: ba6312d19c61
Create Date: 2026-10-27 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c1a2b3d4e5f6'
down_revision = 'ba6312d19c61'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_transfers", sa.Column("status", sa.String(20), nullable=False, server_default="pending"))
    op.create_index("ix_stock_transfers_status", "stock_transfers", ["status"])
    op.add_column("stock_transfers", sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("stock_transfers", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stock_transfers", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_transfers", "rejection_reason")
    op.drop_column("stock_transfers", "approved_at")
    op.drop_column("stock_transfers", "approved_by")
    op.drop_index("ix_stock_transfers_status", table_name="stock_transfers")
    op.drop_column("stock_transfers", "status")