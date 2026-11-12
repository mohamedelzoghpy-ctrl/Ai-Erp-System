"""ETA phase-2 prep: issuer address, receiver TIN, credit-note submissions.

Revision ID: eta2026111102
Revises: eta2026111101
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "eta2026111102"
down_revision = "eta2026111101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("eta_governate", sa.String(length=60), nullable=True))
    op.add_column("companies", sa.Column("eta_region_city", sa.String(length=60), nullable=True))
    op.add_column("companies", sa.Column("eta_street", sa.String(length=120), nullable=True))
    op.add_column("companies", sa.Column("eta_building_number", sa.String(length=20), nullable=True))
    op.add_column("customers", sa.Column("tax_registration_number", sa.String(length=50), nullable=True))
    op.add_column("eta_submissions", sa.Column("return_id", sa.Integer(), sa.ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_eta_submissions_return_id", "eta_submissions", ["return_id"])
    op.alter_column("eta_submissions", "order_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("eta_submissions", "order_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_eta_submissions_return_id", table_name="eta_submissions")
    op.drop_column("eta_submissions", "return_id")
    op.drop_column("customers", "tax_registration_number")
    for col in ("eta_building_number", "eta_street", "eta_region_city", "eta_governate"):
        op.drop_column("companies", col)
