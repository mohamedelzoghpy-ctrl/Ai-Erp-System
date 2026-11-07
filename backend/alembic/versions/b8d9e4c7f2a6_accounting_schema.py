"""accounting schema: chart of accounts, journals, cost centers, fiscal years, fixed assets + supplier codes

Revision ID: b8d9e4c7f2a6
Revises: a48c7f2d9b31
Create Date: 2026-10-31 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b8d9e4c7f2a6"
down_revision = "a48c7f2d9b31"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables(insp):
    return set(insp.get_table_names())


def _columns(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = _inspector()
    tables = _tables(insp)

    # ---------------- chart_accounts ----------------
    if "chart_accounts" not in tables:
        op.create_table(
            "chart_accounts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("parent_id", sa.Integer(), sa.ForeignKey("chart_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("type", sa.String(20), nullable=False),
            sa.Column("is_group", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("company_id", "code", name="uq_coa_company_code"),
        )
        op.create_index("ix_chart_accounts_code", "chart_accounts", ["code"])
        op.create_index("ix_chart_accounts_company_id", "chart_accounts", ["company_id"])
        op.create_index("ix_chart_accounts_parent_id", "chart_accounts", ["parent_id"])

    # ---------------- cost_centers ----------------
    if "cost_centers" not in tables:
        op.create_table(
            "cost_centers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("company_id", "code", name="uq_cc_company_code"),
        )
        op.create_index("ix_cost_centers_code", "cost_centers", ["code"])
        op.create_index("ix_cost_centers_company_id", "cost_centers", ["company_id"])

    # ---------------- fiscal_years ----------------
    if "fiscal_years" not in tables:
        op.create_table(
            "fiscal_years",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("name", sa.String(50), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_fiscal_years_company_id", "fiscal_years", ["company_id"])

    # ---------------- fixed_assets ----------------
    # NOTE: company_id gets a real FK here (the ORM model re-declares it without one).
    if "fixed_assets" not in tables:
        op.create_table(
            "fixed_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("asset_type", sa.String(100), nullable=False),
            sa.Column("purchase_date", sa.Date(), nullable=False),
            sa.Column("cost", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("accumulated_depreciation", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("current_book_value", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("depreciation_method", sa.String(50), nullable=False),
            sa.Column("useful_life_years", sa.Integer(), nullable=False),
            sa.Column("salvage_value", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("company_id", "code", name="uq_fa_company_code"),
        )
        op.create_index("ix_fixed_assets_code", "fixed_assets", ["code"])
        op.create_index("ix_fixed_assets_company_id", "fixed_assets", ["company_id"])

    # ---------------- journal_entries ----------------
    if "journal_entries" not in tables:
        op.create_table(
            "journal_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("reference", sa.String(100), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_journal_entries_company_id", "journal_entries", ["company_id"])

    # ---------------- journal_items ----------------
    if "journal_items" not in tables:
        op.create_table(
            "journal_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("chart_accounts.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("cost_center_id", sa.Integer(), sa.ForeignKey("cost_centers.id"), nullable=True),
            sa.Column("debit", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("credit", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_journal_items_entry_id", "journal_items", ["entry_id"])
        op.create_index("ix_journal_items_account_id", "journal_items", ["account_id"])
        op.create_index("ix_journal_items_cost_center_id", "journal_items", ["cost_center_id"])
        op.create_index("ix_journal_items_company_id", "journal_items", ["company_id"])

    # ---------------- columns on existing tables ----------------
    insp = _inspector()

    # safes.chart_account_id (missing from earlier migrations)
    if "safes" in _tables(insp):
        safe_cols = _columns(insp, "safes")
        if "chart_account_id" not in safe_cols:
            op.add_column("safes", sa.Column("chart_account_id", sa.Integer(), sa.ForeignKey("chart_accounts.id"), nullable=True))
            op.create_index("ix_safes_chart_account_id", "safes", ["chart_account_id"])

    sup_cols = _columns(insp, "suppliers")
    if "code" not in sup_cols:
        # add nullable, backfill deterministic codes, then enforce NOT NULL
        op.add_column("suppliers", sa.Column("code", sa.String(50), nullable=True))
        op.execute("UPDATE suppliers SET code = 'SUP-' || lpad(id::text, 5, '0')")
        op.alter_column("suppliers", "code", existing_type=sa.String(50), nullable=False)
    if "chart_account_id" not in sup_cols:
        op.add_column(
            "suppliers",
            sa.Column("chart_account_id", sa.Integer(), sa.ForeignKey("chart_accounts.id"), nullable=True),
        )
        op.create_index("ix_suppliers_chart_account_id", "suppliers", ["chart_account_id"])
    if not any(c["name"] == "uq_supplier_company_code" for c in insp.get_unique_constraints("suppliers")):
        op.create_unique_constraint("uq_supplier_company_code", "suppliers", ["company_id", "code"])

    cust_cols = _columns(insp, "customers")
    if "chart_account_id" not in cust_cols:
        op.add_column(
            "customers",
            sa.Column("chart_account_id", sa.Integer(), sa.ForeignKey("chart_accounts.id"), nullable=True),
        )
        op.create_index("ix_customers_chart_account_id", "customers", ["chart_account_id"])

    bank_cols = _columns(insp, "banks")
    if "code" not in bank_cols:
        op.add_column("banks", sa.Column("code", sa.String(50), nullable=True))
        op.execute("UPDATE banks SET code = 'BANK-' || lpad(id::text, 5, '0')")
        op.alter_column("banks", "code", existing_type=sa.String(50), nullable=False)
    if "chart_account_id" not in bank_cols:
        op.add_column(
            "banks",
            sa.Column("chart_account_id", sa.Integer(), sa.ForeignKey("chart_accounts.id"), nullable=True),
        )
        op.create_index("ix_banks_chart_account_id", "banks", ["chart_account_id"])
    if not any(c["name"] == "uq_bank_company_code" for c in insp.get_unique_constraints("banks")):
        op.create_unique_constraint("uq_bank_company_code", "banks", ["company_id", "code"])


def downgrade() -> None:
    insp = _inspector()
    tables = _tables(insp)

    if tables:
        bank_cols = _columns(insp, "banks")
        if "chart_account_id" in bank_cols:
            op.drop_index("ix_banks_chart_account_id", table_name="banks")
            op.drop_column("banks", "chart_account_id")
        if "code" in bank_cols:
            op.drop_column("banks", "code")
        if any(c["name"] == "uq_bank_company_code" for c in insp.get_unique_constraints("banks")):
            op.drop_constraint("uq_bank_company_code", "banks", type_="unique")

        cust_cols = _columns(insp, "customers")
        if "chart_account_id" in cust_cols:
            op.drop_index("ix_customers_chart_account_id", table_name="customers")
            op.drop_column("customers", "chart_account_id")

        sup_cols = _columns(insp, "suppliers")
        if "chart_account_id" in sup_cols:
            op.drop_index("ix_suppliers_chart_account_id", table_name="suppliers")
            op.drop_column("suppliers", "chart_account_id")
        if "code" in sup_cols:
            op.drop_column("suppliers", "code")
        if any(c["name"] == "uq_supplier_company_code" for c in insp.get_unique_constraints("suppliers")):
            op.drop_constraint("uq_supplier_company_code", "suppliers", type_="unique")

    for name in ("journal_items", "journal_entries", "fixed_assets", "fiscal_years", "cost_centers", "chart_accounts"):
        if name in _tables(_inspector()):
            op.drop_table(name)
