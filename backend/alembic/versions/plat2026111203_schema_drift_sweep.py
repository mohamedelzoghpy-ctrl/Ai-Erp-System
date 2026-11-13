"""Schema drift sweep: columns and tables added to models without migrations.

Revision ID: plat2026111203
Revises: plat2026111202
Create Date: 2026-11-12 00:00:00.000000

مقارنة منهجية بين Base.metadata والقاعدة الحية كشفت فجوات كانت ستُنتج 500:
- chart_accounts.requires_cost_center (يقرأه محرك القيود في كل ترحيل)
- suppliers.credit_limit (حد ائتمان الموردين)
- hr_attendance.overtime_type / overtime_approved (أوفر تايم الحضور)
- جدولا البصمة biometric_devices / biometric_logs (وحدة HR)
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111203"
down_revision = "plat2026111202"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- أعمدة ناقصة ----
    op.add_column(
        "chart_accounts",
        sa.Column("requires_cost_center", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("suppliers", sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column(
        "hr_attendance",
        sa.Column("overtime_type", sa.String(length=10), nullable=False, server_default="day"),
    )
    op.add_column(
        "hr_attendance",
        sa.Column("overtime_approved", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # ---- أجهزة البصمة ----
    op.create_table(
        "biometric_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("device_model", sa.String(length=50), nullable=True, server_default="ZKTeco"),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="4370"),
        sa.Column("serial_number", sa.String(length=100), nullable=True),
        sa.Column("comm_key", sa.String(length=50), nullable=True, server_default="0"),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "ip_address", "port", name="uq_biometric_device_ip_port"),
    )
    op.create_index("ix_biometric_devices_id", "biometric_devices", ["id"])
    op.create_index("ix_biometric_devices_company_id", "biometric_devices", ["company_id"])
    op.create_index("ix_biometric_devices_branch_id", "biometric_devices", ["branch_id"])

    # ---- سجلات البصمات الخام ----
    op.create_table(
        "biometric_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("employee_code", sa.String(length=50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("punch_type", sa.String(length=10), nullable=False, server_default="auto"),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["biometric_devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_biometric_logs_id", "biometric_logs", ["id"])
    op.create_index("ix_biometric_logs_company_id", "biometric_logs", ["company_id"])
    op.create_index("ix_biometric_logs_device_id", "biometric_logs", ["device_id"])
    op.create_index("ix_biometric_logs_employee_code", "biometric_logs", ["employee_code"])
    op.create_index("ix_biometric_logs_timestamp", "biometric_logs", ["timestamp"])
    op.create_index("ix_biometric_logs_processed", "biometric_logs", ["processed"])
    op.create_index("ix_biometric_logs_emp_time", "biometric_logs", ["company_id", "employee_code", "timestamp"])


def downgrade() -> None:
    op.drop_table("biometric_logs")
    op.drop_table("biometric_devices")
    op.drop_column("hr_attendance", "overtime_approved")
    op.drop_column("hr_attendance", "overtime_type")
    op.drop_column("suppliers", "credit_limit")
    op.drop_column("chart_accounts", "requires_cost_center")
