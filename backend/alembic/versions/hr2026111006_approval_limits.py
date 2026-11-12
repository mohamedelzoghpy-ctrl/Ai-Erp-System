"""HR advance approval limits per user

Revision ID: hr2026111006
Revises: qc2026111005
Create Date: 2026-11-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026111006"
down_revision = "qc2026111005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_advance_approval_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("max_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "user_id", name="uq_hr_advance_limit_user"),
    )
    op.create_index("ix_hr_advance_approval_limits_id", "hr_advance_approval_limits", ["id"])
    op.create_index("ix_hr_advance_approval_limits_company_id", "hr_advance_approval_limits", ["company_id"])
    op.create_index("ix_hr_advance_approval_limits_user_id", "hr_advance_approval_limits", ["user_id"])


def downgrade() -> None:
    op.drop_table("hr_advance_approval_limits")
