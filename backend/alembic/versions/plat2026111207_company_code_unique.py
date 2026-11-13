"""Company code uniqueness — real SaaS requirement caught by isolation tests.

Revision ID: plat2026111207
Revises: plat2026111206
Create Date: 2026-11-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "plat2026111207"
down_revision = "plat2026111206"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # دفاعي: لو وجدت أكواد مكررة تاريخياً نُميزها قبل الفهرس الفريد
    conn = op.get_bind()
    dupes = conn.execute(
        sa.text(
            "SELECT code FROM companies GROUP BY code HAVING COUNT(*) > 1"
        )
    ).fetchall()
    for code, _c in dupes:
        rows = conn.execute(
            sa.text("SELECT id FROM companies WHERE code = :c ORDER BY id"), {"c": code}
        ).fetchall()
        for seq, (cid,) in enumerate(rows[1:], start=1):
            conn.execute(
                sa.text("UPDATE companies SET code = :c WHERE id = :i"),
                {"c": f"{code}-{seq}", "i": cid},
            )
    op.create_unique_constraint("uq_company_code", "companies", ["code"])


def downgrade() -> None:
    op.drop_constraint("uq_company_code", "companies", type_="unique")
