"""CRM م3: client_ref لأنشطة الموبايل (idempotency) — مزامنة القادة أوفلاين.

Revision ID: c2_2026111408
Revises: c2_2026111407
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c2_2026111408"
down_revision = "c2_2026111407"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_activities", sa.Column("client_ref", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_crm_activity_client_ref", "crm_activities", ["company_id", "client_ref"])


def downgrade() -> None:
    op.drop_constraint("uq_crm_activity_client_ref", "crm_activities", type_="unique")
    op.drop_column("crm_activities", "client_ref")
