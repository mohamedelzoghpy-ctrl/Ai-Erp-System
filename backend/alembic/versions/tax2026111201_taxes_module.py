"""موديول الضرائب: أكواد الخصم والإضافة + إعدادات وشرائح ضريبة كسب العمل + حقول السندات.

Revision ID: tax2026111201
Revises: rep2026111201
Create Date: 2026-11-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "tax2026111201"
down_revision = "rep2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "withholding_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "name", name="uq_withholding_code_name"),
    )
    op.create_table(
        "tax_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="payroll", index=True),
        sa.Column("personal_exemption", sa.Numeric(14, 2), nullable=False, server_default="20000"),
        sa.Column("wage_reduction_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("social_insurance_percent", sa.Numeric(5, 2), nullable=False, server_default="11"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "kind", name="uq_tax_setting_kind"),
    )
    op.create_table(
        "tax_brackets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="payroll", index=True),
        sa.Column("min_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("max_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "payments",
        sa.Column("withholding_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "payments",
        sa.Column("withholding_code_id", sa.Integer(), sa.ForeignKey("withholding_codes.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "withholding_code_id")
    op.drop_column("payments", "withholding_amount")
    op.drop_table("tax_brackets")
    op.drop_table("tax_settings")
    op.drop_table("withholding_codes")
