"""Sales-rep mobile kit: login link, devices, notifications.

Revision ID: rep2026111201
Revises: eta2026111203
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "rep2026111201"
down_revision = "eta2026111203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_reps", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.create_unique_constraint("uq_sales_rep_user", "sales_reps", ["user_id"])

    op.create_table(
        "rep_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("rep_id", sa.Integer(), nullable=False),
        sa.Column("fcm_token", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=False, server_default="android"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rep_id"], ["sales_reps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rep_id", "fcm_token", name="uq_rep_device_token"),
    )
    op.create_index("ix_rep_devices_id", "rep_devices", ["id"])
    op.create_index("ix_rep_devices_rep_id", "rep_devices", ["rep_id"])

    op.create_table(
        "rep_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("rep_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="general"),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pushed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rep_id"], ["sales_reps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rep_notifications_id", "rep_notifications", ["id"])
    op.create_index("ix_rep_notif_rep_read", "rep_notifications", ["company_id", "rep_id", "read_at"])


def downgrade() -> None:
    op.drop_table("rep_notifications")
    op.drop_table("rep_devices")
    op.drop_constraint("uq_sales_rep_user", "sales_reps", type_="unique")
    op.drop_column("sales_reps", "user_id")
