"""Company accounting lock date.

Revision ID: plat2026111202
Revises: dev2026111201
Create Date: 2026-11-12 00:00:00.000000

عمودcompanies.accounting_lock_date: تاريخ قفل الحسابات على مستوى الشركة —
تُرفض أي قيود بتاريخ سابق له (طبقة فوق أقفال الفترات الشهرية/السنوية).
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111202"
down_revision = "dev2026111201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("accounting_lock_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "accounting_lock_date")
