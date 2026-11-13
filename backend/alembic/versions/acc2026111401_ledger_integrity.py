"""سلامة الدفاتر على مستوى القاعدة (إصلاح حرج 3 من تدقيق 2026-11-14):

- CHECK على journal_items (هذه الترحيلة، alembic-tracked): بند القيد طرف واحد غير سالب
- مشغّل توازن القيد (مدين = دائن) مؤجَّل على مستوى القاعدة — يُطبَّق من
  backend/scripts/ledger_integrity.sql (يدويًا مرة واحدة بعد الترحيلة، أو ضمن النشر):
  docker compose exec -T db psql -U erp -d erp_db < backend/scripts/ledger_integrity.sql
  (توازن القيد شرط عبر الصفوف لا يُعبَّر عنه بواجهات alembic المهيكلة) —
  الحماية كانت في بايثون فقط قبله

Revision ID: acc2026111401
Revises: inv2026111540
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op

revision = "acc2026111401"
down_revision = "inv2026111540"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # البيانات الحية تحققت يدويًا قبل التطبيق: صفر بنود بطرفين أو سالب، وصفر قيود غير متوازنة
    op.create_check_constraint(
        "ck_journal_item_sides", "journal_items",
        "debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_journal_item_sides", "journal_items", type_="check")
