"""أرشفة إلكترونية (e-Archiving): جدول eta_archives للمستندات المؤرشفة بصيغة XML.

Revision ID: arch2026111201
Revises: tax2026111201
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "arch2026111201"
down_revision = "tax2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eta_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(10), nullable=False),  # submission | incoming
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("eta_submissions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("incoming_id", sa.Integer(), sa.ForeignKey("eta_incoming_documents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("document_type", sa.String(2), nullable=False),
        sa.Column("internal_id", sa.String(60), nullable=False),
        sa.Column("eta_uuid", sa.String(80), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("xml", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="archived", index=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("company_id", "eta_uuid", name="uq_eta_archive_uuid"),
    )
    op.create_index("ix_eta_archive_status", "eta_archives", ["company_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_eta_archive_status", table_name="eta_archives")
    op.drop_table("eta_archives")
