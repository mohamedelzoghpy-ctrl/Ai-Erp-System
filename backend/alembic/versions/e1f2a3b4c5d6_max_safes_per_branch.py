"""add max_safes_per_branch to companies

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-10-27 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("max_safes_per_branch", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "max_safes_per_branch")
