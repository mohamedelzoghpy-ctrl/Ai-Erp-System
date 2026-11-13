"""Bank reconciliation: mark statement lines posted to the ledger.

Revision ID: plat2026111205
Revises: plat2026111204
Create Date: 2026-11-13 00:00:00.000000

عمود bank_statement_lines.posted_in_entry_id: القيود المرحَّلة من كشف البنك
(فروق غير مطابقة) تُوسم برقم قيدها — تمنع الترحيل المزدوج وتوثق الأثر.
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111205"
down_revision = "plat2026111204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_statement_lines", sa.Column("posted_in_entry_id", sa.Integer(), nullable=True))
    op.create_index("ix_bank_statement_lines_posted_in_entry_id", "bank_statement_lines", ["posted_in_entry_id"])


def downgrade() -> None:
    op.drop_index("ix_bank_statement_lines_posted_in_entry_id", table_name="bank_statement_lines")
    op.drop_column("bank_statement_lines", "posted_in_entry_id")
