"""ETA operations: incoming purchase documents ledger.

Revision ID: eta2026111203
Revises: curr2026111201
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "eta2026111203"
down_revision = "curr2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("tax_registration_number", sa.String(length=50), nullable=True))
    op.create_table(
        "eta_incoming_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("eta_uuid", sa.String(length=80), nullable=False),
        sa.Column("issuer_tin", sa.String(length=50), nullable=True),
        sa.Column("issuer_name", sa.String(length=150), nullable=False),
        sa.Column("internal_id", sa.String(length=60), nullable=True),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("imported_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eta_incoming_documents_id", "eta_incoming_documents", ["id"])
    op.create_index("ix_eta_incoming_status", "eta_incoming_documents", ["company_id", "status"])


def downgrade() -> None:
    op.drop_column("suppliers", "tax_registration_number")
    op.drop_table("eta_incoming_documents")
