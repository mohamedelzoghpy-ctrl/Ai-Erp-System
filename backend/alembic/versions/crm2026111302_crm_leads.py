"""CRM خفيف: جدولا العملاء المحتملين وأنشطتهم.

Revision ID: crm2026111302
Revises: fix2026111301
Create Date: 2026-11-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "crm2026111302"
down_revision = "fix2026111301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("company_name", sa.String(length=150), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="walk_in"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("expected_value", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("assigned_rep_id", sa.Integer(), sa.ForeignKey("sales_reps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("converted_customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('new', 'contacted', 'qualified', 'won', 'lost')",
            name="ck_crm_lead_status",
        ),
        sa.UniqueConstraint("company_id", "code", name="uq_crm_lead_company_code"),
    )
    op.create_index("ix_crm_leads_id", "crm_leads", ["id"])
    op.create_index("ix_crm_leads_company_id", "crm_leads", ["company_id"])
    op.create_index("ix_crm_leads_code", "crm_leads", ["code"])
    op.create_index("ix_crm_leads_name", "crm_leads", ["name"])
    op.create_index("ix_crm_leads_status", "crm_leads", ["status"])
    op.create_index("ix_crm_leads_assigned_rep_id", "crm_leads", ["assigned_rep_id"])
    op.create_index("ix_crm_leads_converted_customer_id", "crm_leads", ["converted_customer_id"])

    op.create_table(
        "crm_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="note"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_crm_activities_id", "crm_activities", ["id"])
    op.create_index("ix_crm_activities_company_id", "crm_activities", ["company_id"])
    op.create_index("ix_crm_activities_lead_id", "crm_activities", ["lead_id"])


def downgrade() -> None:
    op.drop_table("crm_activities")
    op.drop_table("crm_leads")
