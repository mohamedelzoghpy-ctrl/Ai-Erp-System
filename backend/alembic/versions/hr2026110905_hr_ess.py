"""HR self-service: attendance corrections by the employee himself

Revision ID: hr2026110905
Revises: hr2026110904
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026110905"
down_revision = "hr2026110904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_attendance_corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("requested_check_in", sa.String(length=5), nullable=True),
        sa.Column("requested_check_out", sa.String(length=5), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("applied_attendance_id", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "employee_id", "work_date", name="uq_hr_attendance_correction_day"),
    )
    op.create_index("ix_hr_attendance_corrections_id", "hr_attendance_corrections", ["id"])
    op.create_index("ix_hr_attendance_corrections_company_id", "hr_attendance_corrections", ["company_id"])
    op.create_index("ix_hr_attendance_corrections_employee_id", "hr_attendance_corrections", ["employee_id"])
    op.create_index("ix_hr_attendance_corrections_work_date", "hr_attendance_corrections", ["work_date"])
    op.create_index("ix_hr_attendance_corrections_status", "hr_attendance_corrections", ["status"])
    op.create_index("ix_hr_att_corr_company_status", "hr_attendance_corrections", ["company_id", "status"])


def downgrade() -> None:
    op.drop_table("hr_attendance_corrections")
