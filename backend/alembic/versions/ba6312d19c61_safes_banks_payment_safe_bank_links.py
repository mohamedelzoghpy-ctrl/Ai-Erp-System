"""safes, banks, payment safe/bank links

Revision ID: ba6312d19c61
Revises: 70e0b79c9139
Create Date: 2026-10-27 03:16:32.140051
"""
from alembic import op
import sqlalchemy as sa


revision = 'ba6312d19c61'
down_revision = '70e0b79c9139'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, index=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "code", name="uq_safe_company_code"),
    )
    op.create_table(
        "banks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, index=True),
        sa.Column("account_number", sa.String(60), nullable=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "code", name="uq_bank_company_code"),
    )
    op.add_column("payments", sa.Column("safe_id", sa.Integer(), sa.ForeignKey("safes.id"), nullable=True))
    op.add_column("payments", sa.Column("bank_id", sa.Integer(), sa.ForeignKey("banks.id"), nullable=True))
    op.create_index("ix_payments_safe_id", "payments", ["safe_id"])
    op.create_index("ix_payments_bank_id", "payments", ["bank_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_bank_id", table_name="payments")
    op.drop_index("ix_payments_safe_id", table_name="payments")
    op.drop_column("payments", "bank_id")
    op.drop_column("payments", "safe_id")
    op.drop_table("banks")
    op.drop_table("safes")
