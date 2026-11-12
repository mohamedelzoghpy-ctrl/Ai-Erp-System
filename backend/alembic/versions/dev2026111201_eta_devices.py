"""أجهزة SDK المسجلة لإيصالات المنظومة: جدول eta_devices + device_id على الإرسالات.

Revision ID: dev2026111201
Revises: arch2026111201
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "dev2026111201"
down_revision = "arch2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eta_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("serial", sa.String(80), nullable=False, index=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("private_key", sa.Text(), nullable=True),
        sa.Column("public_key", sa.Text(), nullable=True),
        sa.Column("csr", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "serial", name="uq_eta_device_serial"),
    )
    op.add_column(
        "eta_submissions",
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("eta_devices.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_eta_submissions_device_id", "eta_submissions", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_eta_submissions_device_id", table_name="eta_submissions")
    op.drop_column("eta_submissions", "device_id")
    op.drop_table("eta_devices")
