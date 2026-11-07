"""customer codes: customers get a real company-scoped code (auto-generated when left empty on import)

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f7
Create Date: 2026-11-01 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5a6b7'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.add_column(sa.Column("code", sa.String(50), nullable=True))
    # Seed deterministic codes for existing rows, then make it a required column.
    op.execute("UPDATE customers SET code = 'CUS-' || CAST(id AS TEXT) WHERE code IS NULL")
    with op.batch_alter_table("customers") as batch:
        batch.alter_column("code", existing_type=sa.String(50), nullable=False)
    op.create_index("ix_customers_code", "customers", ["code"])
    op.create_unique_constraint("uq_customer_company_code", "customers", ["company_id", "code"])


def downgrade() -> None:
    op.drop_constraint("uq_customer_company_code", "customers", type_="unique")
    op.drop_index("ix_customers_code", table_name="customers")
    with op.batch_alter_table("customers") as batch:
        batch.drop_column("code")
