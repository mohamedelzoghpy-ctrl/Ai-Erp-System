"""add company departments

Revision ID: d9f4a1b6c832
Revises: c2d3e4f5a6b7
Create Date: 2026-11-01 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d9f4a1b6c832"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_department_company_code"),
        sa.UniqueConstraint("company_id", "name", name="uq_department_company_name"),
    )
    op.create_index("ix_departments_id", "departments", ["id"])
    op.create_index("ix_departments_company_id", "departments", ["company_id"])
    op.create_index("ix_departments_name", "departments", ["name"])
    op.create_index("ix_departments_code", "departments", ["code"])


def downgrade() -> None:
    op.drop_index("ix_departments_code", table_name="departments")
    op.drop_index("ix_departments_name", table_name="departments")
    op.drop_index("ix_departments_company_id", table_name="departments")
    op.drop_index("ix_departments_id", table_name="departments")
    op.drop_table("departments")
