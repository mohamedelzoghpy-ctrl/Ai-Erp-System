"""HR payroll: salary components, payroll runs, payslips and payslip lines

Revision ID: hr2026110903
Revises: hr2026110902
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026110903"
down_revision = "hr2026110902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_salary_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("amount_mode", sa.String(length=16), server_default="fixed", nullable=False),
        sa.Column("fixed_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("percent_value", sa.Numeric(5, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "employee_id", "name", name="uq_hr_salary_component_employee_name"),
        sa.CheckConstraint("percent_value IS NULL OR (percent_value >= 0 AND percent_value <= 100)", name="ck_hr_salary_component_percent"),
        sa.CheckConstraint("fixed_amount IS NULL OR fixed_amount >= 0", name="ck_hr_salary_component_amount"),
    )
    op.create_index("ix_hr_salary_components_id", "hr_salary_components", ["id"])
    op.create_index("ix_hr_salary_components_company_id", "hr_salary_components", ["company_id"])
    op.create_index("ix_hr_salary_components_employee_id", "hr_salary_components", ["employee_id"])
    op.create_index("ix_hr_salary_components_category", "hr_salary_components", ["category"])

    op.create_table(
        "hr_payroll_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="draft", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("employees_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_gross", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_deductions", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_net", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("posted_by", sa.Integer(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "year", "month", name="uq_hr_payroll_run_period"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_hr_payroll_run_month"),
    )
    op.create_index("ix_hr_payroll_runs_id", "hr_payroll_runs", ["id"])
    op.create_index("ix_hr_payroll_runs_company_id", "hr_payroll_runs", ["company_id"])
    op.create_index("ix_hr_payroll_runs_year", "hr_payroll_runs", ["year"])
    op.create_index("ix_hr_payroll_runs_month", "hr_payroll_runs", ["month"])
    op.create_index("ix_hr_payroll_runs_status", "hr_payroll_runs", ["status"])
    op.create_index("ix_hr_payroll_runs_journal_entry_id", "hr_payroll_runs", ["journal_entry_id"])
    op.create_index("ix_hr_payroll_runs_company_status", "hr_payroll_runs", ["company_id", "status"])

    op.create_table(
        "hr_payslips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("base_salary", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("absent_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unpaid_leave_days", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("absence_deduction", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_earnings", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_deductions", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("net_pay", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["hr_payroll_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "employee_id", name="uq_hr_payslip_run_employee"),
    )
    op.create_index("ix_hr_payslips_id", "hr_payslips", ["id"])
    op.create_index("ix_hr_payslips_company_id", "hr_payslips", ["company_id"])
    op.create_index("ix_hr_payslips_run_id", "hr_payslips", ["run_id"])
    op.create_index("ix_hr_payslips_employee_id", "hr_payslips", ["employee_id"])

    op.create_table(
        "hr_payslip_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("payslip_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payslip_id"], ["hr_payslips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hr_payslip_lines_id", "hr_payslip_lines", ["id"])
    op.create_index("ix_hr_payslip_lines_payslip", "hr_payslip_lines", ["payslip_id"])


def downgrade() -> None:
    op.drop_table("hr_payslip_lines")
    op.drop_table("hr_payslips")
    op.drop_table("hr_payroll_runs")
    op.drop_table("hr_salary_components")
