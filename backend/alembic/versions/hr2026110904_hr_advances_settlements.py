"""HR advances & final settlements + WPS traceability on payslip lines

Revision ID: hr2026110904
Revises: hr2026110903
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026110904"
down_revision = "hr2026110903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_advances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("installments_count", sa.Integer(), nullable=False),
        sa.Column("start_year", sa.Integer(), nullable=False),
        sa.Column("start_month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="ck_hr_advance_amount_positive"),
        sa.CheckConstraint("installments_count >= 1 AND installments_count <= 240", name="ck_hr_advance_installments"),
        sa.CheckConstraint("start_month >= 1 AND start_month <= 12", name="ck_hr_advance_start_month"),
    )
    op.create_index("ix_hr_advances_id", "hr_advances", ["id"])
    op.create_index("ix_hr_advances_company_id", "hr_advances", ["company_id"])
    op.create_index("ix_hr_advances_employee_id", "hr_advances", ["employee_id"])
    op.create_index("ix_hr_advances_start_year", "hr_advances", ["start_year"])
    op.create_index("ix_hr_advances_status", "hr_advances", ["status"])
    op.create_index("ix_hr_advances_company_status", "hr_advances", ["company_id", "status"])

    # تتبّع أقساط السلف داخل سطور القسائم (بعد وجود جدول hr_advances)
    op.add_column("hr_payslip_lines", sa.Column("advance_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_hr_payslip_lines_advance", "hr_payslip_lines", "hr_advances",
        ["advance_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "hr_settlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("termination_date", sa.Date(), nullable=False),
        sa.Column("service_days", sa.Integer(), nullable=False),
        sa.Column("service_years", sa.Numeric(8, 2), nullable=False),
        sa.Column("eosb_days", sa.Numeric(8, 1), nullable=False),
        sa.Column("eosb_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("unused_leave_days", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("unused_leave_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("advances_remaining", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_due", sa.Numeric(14, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "employee_id", name="uq_hr_settlement_employee"),
    )
    op.create_index("ix_hr_settlements_id", "hr_settlements", ["id"])
    op.create_index("ix_hr_settlements_company_id", "hr_settlements", ["company_id"])
    op.create_index("ix_hr_settlements_employee_id", "hr_settlements", ["employee_id"])


def downgrade() -> None:
    op.drop_table("hr_settlements")
    op.drop_table("hr_advances")
    op.drop_constraint("fk_hr_payslip_lines_advance", "hr_payslip_lines", type_="foreignkey")
    op.drop_column("hr_payslip_lines", "advance_id")
