"""add department and branch scope to company memberships

Revision ID: ef16b42a9c70
Revises: d9f4a1b6c832
Create Date: 2026-11-01 17:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "ef16b42a9c70"
down_revision = "d9f4a1b6c832"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_company_memberships", sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("user_company_memberships", sa.Column("all_branches", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_index("ix_user_company_memberships_department_id", "user_company_memberships", ["department_id"])
    op.create_foreign_key(
        "fk_user_company_memberships_department_id_departments",
        "user_company_memberships",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_company_memberships_department_id_departments", "user_company_memberships", type_="foreignkey")
    op.drop_index("ix_user_company_memberships_department_id", table_name="user_company_memberships")
    op.drop_column("user_company_memberships", "all_branches")
    op.drop_column("user_company_memberships", "department_id")
