"""CRM م4: مهام مجدولة على القادة — due_at/done_at للأنشطة.

Revision ID: c2_2026111409
Revises: c2_2026111408
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c2_2026111409"
down_revision = "c2_2026111408"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_activities", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_activities", sa.Column("done_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("crm_activities", "done_at")
    op.drop_column("crm_activities", "due_at")
