"""HR S6: recruiting (ATS), performance reviews, trainings

Revision ID: hr2026110906
Revises: hr2026110905
Create Date: 2026-11-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "hr2026110906"
down_revision = "hr2026110905"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # إعلانات التوظيف (لا FK لاعتماداً على جداول أخرى)
    op.create_table(
        "hr_job_postings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("openings", sa.Integer(), server_default="1", nullable=False),
        sa.Column("employment_type", sa.String(length=20), server_default="full_time", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("hired_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_hr_job_posting_code"),
    )
    op.create_index("ix_hr_job_postings_id", "hr_job_postings", ["id"])
    op.create_index("ix_hr_job_postings_company_id", "hr_job_postings", ["company_id"])
    op.create_index("ix_hr_job_postings_code", "hr_job_postings", ["code"])
    op.create_index("ix_hr_job_postings_status", "hr_job_postings", ["status"])
    op.create_index("ix_hr_job_posting_company_status", "hr_job_postings", ["company_id", "status"])

    # المتقدمون — بعد hr_job_postings (FK posting) وhr_employees (موجود مسبقاً)
    op.create_table(
        "hr_job_applicants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("resume_text", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(length=20), server_default="applied", nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("hired_employee_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posting_id"], ["hr_job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hired_employee_id"], ["hr_employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "posting_id", "email", name="uq_hr_applicant_posting_email"),
    )
    op.create_index("ix_hr_job_applicants_id", "hr_job_applicants", ["id"])
    op.create_index("ix_hr_job_applicants_company_id", "hr_job_applicants", ["company_id"])
    op.create_index("ix_hr_job_applicants_posting_id", "hr_job_applicants", ["posting_id"])
    op.create_index("ix_hr_job_applicants_stage", "hr_job_applicants", ["stage"])
    op.create_index("ix_hr_applicant_company_stage", "hr_job_applicants", ["company_id", "stage"])

    # دورات تقييم الأداء
    op.create_table(
        "hr_review_cycles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_hr_review_cycle_name"),
    )
    op.create_index("ix_hr_review_cycles_id", "hr_review_cycles", ["id"])
    op.create_index("ix_hr_review_cycles_company_id", "hr_review_cycles", ["company_id"])
    op.create_index("ix_hr_review_cycles_name", "hr_review_cycles", ["name"])
    op.create_index("ix_hr_review_cycles_status", "hr_review_cycles", ["status"])

    # التقييمات — بعد hr_review_cycles وhr_employees
    op.create_table(
        "hr_performance_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("cycle_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("commitment", sa.Integer(), nullable=False),
        sa.Column("teamwork", sa.Integer(), nullable=False),
        sa.Column("initiative", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cycle_id"], ["hr_review_cycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "cycle_id", "employee_id", name="uq_hr_review_cycle_employee"),
    )
    op.create_index("ix_hr_performance_reviews_id", "hr_performance_reviews", ["id"])
    op.create_index("ix_hr_performance_reviews_company_id", "hr_performance_reviews", ["company_id"])
    op.create_index("ix_hr_performance_reviews_cycle_id", "hr_performance_reviews", ["cycle_id"])
    op.create_index("ix_hr_performance_reviews_employee_id", "hr_performance_reviews", ["employee_id"])

    # الدورات التدريبية
    op.create_table(
        "hr_trainings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=150), nullable=True),
        sa.Column("location", sa.String(length=150), nullable=True),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("cost", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_hr_training_code"),
    )
    op.create_index("ix_hr_trainings_id", "hr_trainings", ["id"])
    op.create_index("ix_hr_trainings_company_id", "hr_trainings", ["company_id"])
    op.create_index("ix_hr_trainings_code", "hr_trainings", ["code"])

    # تسجيلات الدورات — بعد hr_trainings وhr_employees
    op.create_table(
        "hr_training_enrollments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("training_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=15), server_default="enrolled", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["training_id"], ["hr_trainings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "training_id", "employee_id", name="uq_hr_enroll_training_employee"),
    )
    op.create_index("ix_hr_training_enrollments_id", "hr_training_enrollments", ["id"])
    op.create_index("ix_hr_training_enrollments_company_id", "hr_training_enrollments", ["company_id"])
    op.create_index("ix_hr_training_enrollments_training_id", "hr_training_enrollments", ["training_id"])
    op.create_index("ix_hr_training_enrollments_employee_id", "hr_training_enrollments", ["employee_id"])
    op.create_index("ix_hr_training_enrollments_status", "hr_training_enrollments", ["status"])


def downgrade() -> None:
    op.drop_table("hr_training_enrollments")
    op.drop_table("hr_trainings")
    op.drop_table("hr_performance_reviews")
    op.drop_table("hr_review_cycles")
    op.drop_table("hr_job_applicants")
    op.drop_table("hr_job_postings")
