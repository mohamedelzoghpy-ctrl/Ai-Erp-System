"""HR foundation: job titles, grades, employees, contracts, documents, moves

Revision ID: hr2026110901
Revises: hr000merge
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026110901"
down_revision = "hr000merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_job_titles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("min_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("max_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_hr_job_title_company_name"),
    )
    op.create_index("ix_hr_job_titles_id", "hr_job_titles", ["id"])
    op.create_index("ix_hr_job_titles_company_id", "hr_job_titles", ["company_id"])
    op.create_index("ix_hr_job_titles_name", "hr_job_titles", ["name"])

    op.create_table(
        "hr_grades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("min_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("max_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_hr_grade_company_name"),
    )
    op.create_index("ix_hr_grades_id", "hr_grades", ["id"])
    op.create_index("ix_hr_grades_company_id", "hr_grades", ["company_id"])
    op.create_index("ix_hr_grades_name", "hr_grades", ["name"])

    op.create_table(
        "hr_employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("national_id", sa.String(length=40), nullable=True),
        sa.Column("gender", sa.String(length=10), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=80), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("job_title_id", sa.Integer(), nullable=True),
        sa.Column("grade_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("hire_date", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("basic_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("bank_account", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("terminated_at", sa.Date(), nullable=True),
        sa.Column("termination_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_title_id"], ["hr_job_titles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["grade_id"], ["hr_grades.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["manager_id"], ["hr_employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_hr_employee_company_code"),
        sa.UniqueConstraint("company_id", "national_id", name="uq_hr_employee_company_national_id"),
        sa.CheckConstraint("basic_salary IS NULL OR basic_salary >= 0", name="ck_hr_employee_salary_positive"),
    )
    op.create_index("ix_hr_employees_id", "hr_employees", ["id"])
    op.create_index("ix_hr_employees_company_id", "hr_employees", ["company_id"])
    op.create_index("ix_hr_employees_code", "hr_employees", ["code"])
    op.create_index("ix_hr_employees_full_name", "hr_employees", ["full_name"])
    op.create_index("ix_hr_employees_department_id", "hr_employees", ["department_id"])
    op.create_index("ix_hr_employees_job_title_id", "hr_employees", ["job_title_id"])
    op.create_index("ix_hr_employees_grade_id", "hr_employees", ["grade_id"])
    op.create_index("ix_hr_employees_branch_id", "hr_employees", ["branch_id"])
    op.create_index("ix_hr_employees_manager_id", "hr_employees", ["manager_id"])
    op.create_index("ix_hr_employees_user_id", "hr_employees", ["user_id"])
    op.create_index("ix_hr_employees_status", "hr_employees", ["status"])
    op.create_index("ix_hr_employees_company_status", "hr_employees", ["company_id", "status"])

    op.create_table(
        "hr_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="unlimited", nullable=False),
        sa.Column("start_date", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("basic_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_hr_contract_company_code"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_hr_contract_dates"),
    )
    op.create_index("ix_hr_contracts_id", "hr_contracts", ["id"])
    op.create_index("ix_hr_contracts_company_id", "hr_contracts", ["company_id"])
    op.create_index("ix_hr_contracts_employee_id", "hr_contracts", ["employee_id"])
    op.create_index("ix_hr_contracts_code", "hr_contracts", ["code"])
    op.create_index("ix_hr_contracts_kind", "hr_contracts", ["kind"])
    op.create_index("ix_hr_contracts_status", "hr_contracts", ["status"])

    op.create_table(
        "hr_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=30), server_default="other", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_blob", sa.LargeBinary(), nullable=True),
        sa.Column("file_mime", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hr_documents_id", "hr_documents", ["id"])
    op.create_index("ix_hr_documents_company_id", "hr_documents", ["company_id"])
    op.create_index("ix_hr_documents_employee_id", "hr_documents", ["employee_id"])
    op.create_index("ix_hr_documents_doc_type", "hr_documents", ["doc_type"])
    op.create_index("ix_hr_documents_expiry_date", "hr_documents", ["expiry_date"])

    op.create_table(
        "hr_employee_moves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("move_type", sa.String(length=20), nullable=False),
        sa.Column("effective_date", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("from_department_id", sa.Integer(), nullable=True),
        sa.Column("to_department_id", sa.Integer(), nullable=True),
        sa.Column("from_job_title_id", sa.Integer(), nullable=True),
        sa.Column("to_job_title_id", sa.Integer(), nullable=True),
        sa.Column("from_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("to_salary", sa.Numeric(14, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_job_title_id"], ["hr_job_titles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_job_title_id"], ["hr_job_titles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hr_employee_moves_id", "hr_employee_moves", ["id"])
    op.create_index("ix_hr_employee_moves_company_id", "hr_employee_moves", ["company_id"])
    op.create_index("ix_hr_employee_moves_employee_id", "hr_employee_moves", ["employee_id"])
    op.create_index("ix_hr_employee_moves_move_type", "hr_employee_moves", ["move_type"])


def downgrade() -> None:
    op.drop_table("hr_employee_moves")
    op.drop_table("hr_documents")
    op.drop_table("hr_contracts")
    op.drop_index("ix_hr_employees_company_status", table_name="hr_employees")
    op.drop_table("hr_employees")
    op.drop_table("hr_grades")
    op.drop_table("hr_job_titles")
