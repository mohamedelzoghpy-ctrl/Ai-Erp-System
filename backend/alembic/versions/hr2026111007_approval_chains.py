"""Multi-level approval chains + leave approval_level + employee insurance_number

Revision ID: hr2026111007
Revises: hr2026111006
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026111007"
down_revision = "hr2026111006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_leave_requests", sa.Column("approval_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("hr_employees", sa.Column("insurance_number", sa.String(length=40), nullable=True))

    op.create_table(
        "hr_approval_chains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=10), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=True),
        sa.Column("approver_role", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "entity_type", "level", name="uq_hr_approval_chain_level"),
    )
    op.create_index("ix_hr_approval_chains_id", "hr_approval_chains", ["id"])
    op.create_index("ix_hr_approval_chains_company_id", "hr_approval_chains", ["company_id"])
    op.create_index("ix_hr_approval_chains_entity_type", "hr_approval_chains", ["entity_type"])
    op.create_index("ix_hr_approval_chains_approver_user_id", "hr_approval_chains", ["approver_user_id"])

    op.create_table(
        "hr_approval_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=10), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hr_approval_steps_id", "hr_approval_steps", ["id"])
    op.create_index("ix_hr_approval_steps_company_id", "hr_approval_steps", ["company_id"])
    op.create_index("ix_hr_approval_steps_entity", "hr_approval_steps", ["company_id", "entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("hr_approval_steps")
    op.drop_table("hr_approval_chains")
    op.drop_column("hr_employees", "insurance_number")
    op.drop_column("hr_leave_requests", "approval_level")
