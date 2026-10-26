"""multi-company membership + active company

Revision ID: 70e0b79c9139
Revises: 0013
Create Date: 2026-10-27 02:20:47.800882
"""
from alembic import op
import sqlalchemy as sa


revision = '70e0b79c9139'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_user_company_membership", "user_company_memberships", type_="unique")
    op.add_column("users", sa.Column("active_company_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_active_company", "users", "companies", ["active_company_id"], ["id"], ondelete="SET NULL")
    # Backfill: set active_company_id from the user's (single) membership.
    op.execute(
        "UPDATE users SET active_company_id = (SELECT company_id FROM user_company_memberships WHERE user_id = users.id LIMIT 1)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_active_company", "users", type_="foreignkey")
    op.drop_column("users", "active_company_id")
    op.create_unique_constraint("uq_user_company_membership", "user_company_memberships", ["user_id"])
