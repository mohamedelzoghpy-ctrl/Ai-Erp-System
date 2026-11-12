"""Accounting upgrades 2026-11: VAT fields, JE approval status, fiscal periods,
recurring journals, attachments, bank statement lines.

Revision ID: acc2026111101
Revises: hr2026111007
Create Date: 2026-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "acc2026111101"
down_revision = "hr2026111007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Sales orders: VAT columns (subtotal NULL = legacy order predates VAT)
    op.add_column("sales_orders", sa.Column("subtotal", sa.Numeric(14, 2), nullable=True))
    op.add_column("sales_orders", sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("sales_orders", sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))

    # 2) Journal entries: maker-checker status
    op.add_column("journal_entries", sa.Column("status", sa.String(length=20), nullable=False, server_default="posted"))
    op.add_column("journal_entries", sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("journal_entries", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"])

    # 3) Monthly fiscal periods
    op.create_table(
        "fiscal_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_year_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fiscal_year_id"], ["fiscal_years.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "fiscal_year_id", "start_date", name="uq_fiscal_period_start"),
    )
    op.create_index("ix_fiscal_periods_id", "fiscal_periods", ["id"])
    op.create_index("ix_fiscal_periods_fiscal_year_id", "fiscal_periods", ["fiscal_year_id"])

    # 4) Recurring journal templates
    op.create_table(
        "recurring_journals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("day_of_month", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("last_run_entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurring_journals_id", "recurring_journals", ["id"])
    op.create_index("ix_recurring_journals_company_id", "recurring_journals", ["company_id"])

    # 5) Attachments
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False, server_default="application/octet-stream"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachments_id", "attachments", ["id"])
    op.create_index("ix_attachments_entity", "attachments", ["company_id", "entity_type", "entity_id"])

    # 6) Bank statement lines
    op.create_table(
        "bank_statement_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bank_id", sa.Integer(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("matched_payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("imported_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_id"], ["banks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_statement_lines_id", "bank_statement_lines", ["id"])
    op.create_index("ix_bank_stmt_bank_date", "bank_statement_lines", ["company_id", "bank_id", "value_date"])


def downgrade() -> None:
    op.drop_table("bank_statement_lines")
    op.drop_table("attachments")
    op.drop_table("recurring_journals")
    op.drop_table("fiscal_periods")
    op.drop_index("ix_journal_entries_status", table_name="journal_entries")
    op.drop_column("journal_entries", "approved_at")
    op.drop_column("journal_entries", "approved_by")
    op.drop_column("journal_entries", "status")
    op.drop_column("sales_orders", "tax_amount")
    op.drop_column("sales_orders", "tax_rate")
    op.drop_column("sales_orders", "subtotal")
