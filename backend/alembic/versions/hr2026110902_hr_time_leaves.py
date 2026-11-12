"""HR time & leaves: shifts, assignments, attendance, holidays, leave types/balances/requests

Revision ID: hr2026110902
Revises: hr2026110901
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026110902"
down_revision = "hr2026110901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_shifts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("cross_midnight", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_hr_shift_company_name"),
    )
    op.create_index("ix_hr_shifts_id", "hr_shifts", ["id"])
    op.create_index("ix_hr_shifts_company_id", "hr_shifts", ["company_id"])
    op.create_index("ix_hr_shifts_name", "hr_shifts", ["name"])

    op.create_table(
        "hr_shift_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shift_id"], ["hr_shifts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "employee_id", name="uq_hr_shift_assignment_employee"),
    )
    op.create_index("ix_hr_shift_assignments_id", "hr_shift_assignments", ["id"])
    op.create_index("ix_hr_shift_assignments_company_id", "hr_shift_assignments", ["company_id"])
    op.create_index("ix_hr_shift_assignments_employee_id", "hr_shift_assignments", ["employee_id"])
    op.create_index("ix_hr_shift_assignments_shift_id", "hr_shift_assignments", ["shift_id"])

    op.create_table(
        "hr_attendance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="present", nullable=False),
        sa.Column("check_in", sa.String(length=5), nullable=True),
        sa.Column("check_out", sa.String(length=5), nullable=True),
        sa.Column("late_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("overtime_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=10), server_default="manual", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "employee_id", "work_date", name="uq_hr_attendance_day"),
    )
    op.create_index("ix_hr_attendance_id", "hr_attendance", ["id"])
    op.create_index("ix_hr_attendance_company_id", "hr_attendance", ["company_id"])
    op.create_index("ix_hr_attendance_employee_id", "hr_attendance", ["employee_id"])
    op.create_index("ix_hr_attendance_work_date", "hr_attendance", ["work_date"])
    op.create_index("ix_hr_attendance_status", "hr_attendance", ["status"])
    op.create_index("ix_hr_attendance_source", "hr_attendance", ["source"])
    op.create_index("ix_hr_attendance_company_date", "hr_attendance", ["company_id", "work_date"])

    op.create_table(
        "hr_holidays",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "holiday_date", name="uq_hr_holiday_company_date"),
    )
    op.create_index("ix_hr_holidays_id", "hr_holidays", ["id"])
    op.create_index("ix_hr_holidays_company_id", "hr_holidays", ["company_id"])
    op.create_index("ix_hr_holidays_holiday_date", "hr_holidays", ["holiday_date"])

    op.create_table(
        "hr_leave_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("days_per_year", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("is_paid", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("carry_over_days", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_hr_leave_type_company_name"),
    )
    op.create_index("ix_hr_leave_types_id", "hr_leave_types", ["id"])
    op.create_index("ix_hr_leave_types_company_id", "hr_leave_types", ["company_id"])
    op.create_index("ix_hr_leave_types_name", "hr_leave_types", ["name"])

    op.create_table(
        "hr_leave_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("leave_type_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("entitled_days", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("carried_days", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("used_days", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["leave_type_id"], ["hr_leave_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "employee_id", "leave_type_id", "year", name="uq_hr_leave_balance"),
    )
    op.create_index("ix_hr_leave_balances_id", "hr_leave_balances", ["id"])
    op.create_index("ix_hr_leave_balances_company_id", "hr_leave_balances", ["company_id"])
    op.create_index("ix_hr_leave_balances_employee_id", "hr_leave_balances", ["employee_id"])
    op.create_index("ix_hr_leave_balances_leave_type_id", "hr_leave_balances", ["leave_type_id"])
    op.create_index("ix_hr_leave_balances_year", "hr_leave_balances", ["year"])

    op.create_table(
        "hr_leave_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("leave_type_id", sa.Integer(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Numeric(5, 1), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["leave_type_id"], ["hr_leave_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("to_date >= from_date", name="ck_hr_leave_request_dates"),
        sa.CheckConstraint("days > 0", name="ck_hr_leave_request_days_positive"),
    )
    op.create_index("ix_hr_leave_requests_id", "hr_leave_requests", ["id"])
    op.create_index("ix_hr_leave_requests_company_id", "hr_leave_requests", ["company_id"])
    op.create_index("ix_hr_leave_requests_employee_id", "hr_leave_requests", ["employee_id"])
    op.create_index("ix_hr_leave_requests_leave_type_id", "hr_leave_requests", ["leave_type_id"])
    op.create_index("ix_hr_leave_requests_from_date", "hr_leave_requests", ["from_date"])
    op.create_index("ix_hr_leave_requests_to_date", "hr_leave_requests", ["to_date"])
    op.create_index("ix_hr_leave_requests_status", "hr_leave_requests", ["status"])
    op.create_index("ix_hr_leave_requests_company_status", "hr_leave_requests", ["company_id", "status"])


def downgrade() -> None:
    op.drop_table("hr_leave_requests")
    op.drop_table("hr_leave_balances")
    op.drop_table("hr_leave_types")
    op.drop_table("hr_holidays")
    op.drop_table("hr_attendance")
    op.drop_table("hr_shift_assignments")
    op.drop_table("hr_shifts")
