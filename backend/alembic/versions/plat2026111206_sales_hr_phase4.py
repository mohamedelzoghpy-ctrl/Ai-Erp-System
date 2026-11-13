"""Phase 4: sales discounts, quotation status, commission runs, EOSB posting.

Revision ID: plat2026111206
Revises: plat2026111205
Create Date: 2026-11-13 00:00:00.000000

- sales_orders.discount_amount: خصم على مستوى الأوردر (يُخصم قبل الضريبة)
- sales_orders.commission_run_id: قفل الأوردرات ضمن دورة عمولات (منع الصرف المزدوج)
- rep_commission_runs + rep_commission_run_lines: دورات صرف العمولات
- hr_settlements.status + journal_entry_id: ترحيل تسوية نهاية الخدمة على GL
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111206"
down_revision = "plat2026111205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_orders", sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("sales_orders", sa.Column("commission_run_id", sa.Integer(), nullable=True))
    op.create_index("ix_sales_orders_commission_run_id", "sales_orders", ["commission_run_id"])
    op.add_column("sales_returns", sa.Column("commission_run_id", sa.Integer(), nullable=True))
    op.create_index("ix_sales_returns_commission_run_id", "sales_returns", ["commission_run_id"])

    op.create_table(
        "rep_commission_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="posted"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rep_commission_runs_id", "rep_commission_runs", ["id"])
    op.create_index("ix_rep_commission_runs_company_id", "rep_commission_runs", ["company_id"])

    op.create_table(
        "rep_commission_run_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("rep_commission_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rep_id", sa.Integer(), sa.ForeignKey("sales_reps.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("orders_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("returns_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("net", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("commission", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rep_commission_run_lines_id", "rep_commission_run_lines", ["id"])
    op.create_index("ix_rep_commission_run_lines_run_id", "rep_commission_run_lines", ["run_id"])

    op.add_column("hr_settlements", sa.Column("status", sa.String(20), nullable=False, server_default="draft"))
    op.add_column("hr_settlements", sa.Column("journal_entry_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("hr_settlements", "journal_entry_id")
    op.drop_column("hr_settlements", "status")
    op.drop_table("rep_commission_run_lines")
    op.drop_table("rep_commission_runs")
    op.drop_index("ix_sales_returns_commission_run_id", table_name="sales_returns")
    op.drop_column("sales_returns", "commission_run_id")
    op.drop_index("ix_sales_orders_commission_run_id", table_name="sales_orders")
    op.drop_column("sales_orders", "commission_run_id")
    op.drop_column("sales_orders", "discount_amount")
