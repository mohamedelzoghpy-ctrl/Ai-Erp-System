"""add valuation column to stock_transfers

Revision ID: d5e6f7a8b9c0
Revises: c1a2b3d4e5f6
Create Date: 2026-10-27 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c1a2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_transfers", sa.Column("valuation", sa.String(10), nullable=False, server_default="cost"))


def downgrade() -> None:
    op.drop_column("stock_transfers", "valuation")