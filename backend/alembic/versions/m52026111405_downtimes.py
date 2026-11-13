"""المرحلة 5: توقفات خطوط الإنتاج (للمؤشر المبسط للتوافر).

Revision ID: m52026111405
Revises: m42026111404
Create Date: 2026-11-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "m52026111405"
down_revision = "m42026111404"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_downtimes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("production_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_production_downtimes_id", "production_downtimes", ["id"])
    op.create_index("ix_production_downtimes_company_id", "production_downtimes", ["company_id"])
    op.create_index("ix_production_downtimes_line_id", "production_downtimes", ["line_id"])


def downgrade() -> None:
    op.drop_table("production_downtimes")
