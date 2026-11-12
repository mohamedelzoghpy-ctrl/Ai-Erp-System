"""merge multiple alembic heads (routing_operations + membership employee_code)

Revision ID: hr000merge
Revises: l1m2n3o4p5q6, f482c19a7d31
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr000merge"
down_revision = ("l1m2n3o4p5q6", "f482c19a7d31")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge head only — no schema changes."""


def downgrade() -> None:
    """Nothing to downgrade: merging heads is purely organizational."""
