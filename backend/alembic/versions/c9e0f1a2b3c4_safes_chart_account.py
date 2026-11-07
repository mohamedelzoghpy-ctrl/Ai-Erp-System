"""add chart_account_id to safes

Revision ID: c9e0f1a2b3c4
Revises: b8d9e4c7f2a6
Create Date: 2026-10-31 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e0f1a2b3c4"
down_revision = "b8d9e4c7f2a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("safes")}
    if "chart_account_id" not in cols:
        op.add_column(
            "safes",
            sa.Column("chart_account_id", sa.Integer(), sa.ForeignKey("chart_accounts.id"), nullable=True),
        )
        op.create_index("ix_safes_chart_account_id", "safes", ["chart_account_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("safes")}
    if "chart_account_id" in cols:
        op.drop_index("ix_safes_chart_account_id", table_name="safes")
        op.drop_column("safes", "chart_account_id")
