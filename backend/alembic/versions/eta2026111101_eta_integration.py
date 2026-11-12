"""ETA e-invoicing foundation: company config + submissions ledger.

Revision ID: eta2026111101
Revises: inv2026111101
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "eta2026111101"
down_revision = "inv2026111101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("eta_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("companies", sa.Column("eta_env", sa.String(length=10), nullable=False, server_default="mock"))
    op.add_column("companies", sa.Column("eta_tin", sa.String(length=50), nullable=True))
    op.add_column("companies", sa.Column("eta_client_id", sa.String(length=120), nullable=True))
    op.add_column("companies", sa.Column("eta_client_secret", sa.String(length=255), nullable=True))
    op.add_column("companies", sa.Column("eta_private_key", sa.Text(), nullable=True))
    op.add_column("companies", sa.Column("eta_activity_code", sa.String(length=20), nullable=True, server_default="4690"))

    op.create_table(
        "eta_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=2), nullable=False, server_default="I"),
        sa.Column("internal_id", sa.String(length=60), nullable=False),
        sa.Column("submission_uuid", sa.String(length=80), nullable=True),
        sa.Column("eta_uuid", sa.String(length=80), nullable=True),
        sa.Column("eta_long_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eta_submissions_id", "eta_submissions", ["id"])
    op.create_index("ix_eta_submissions_order_id", "eta_submissions", ["order_id"])
    op.create_index("ix_eta_submissions_status", "eta_submissions", ["status"])
    op.create_index("ix_eta_company_order", "eta_submissions", ["company_id", "order_id"])


def downgrade() -> None:
    op.drop_table("eta_submissions")
    for col in ("eta_activity_code", "eta_private_key", "eta_client_secret", "eta_client_id",
                "eta_tin", "eta_env", "eta_enabled"):
        op.drop_column("companies", col)
