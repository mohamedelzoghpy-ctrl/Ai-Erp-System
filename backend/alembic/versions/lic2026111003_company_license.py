"""Company usage license: license_until (NULL = unrestricted)

Revision ID: lic2026111003
Revises: perm2026111002
Create Date: 2026-11-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "lic2026111003"
down_revision = "perm2026111002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # رخصة الاستخدام لكل شركة: تاريخ الانتهاء (NULL = غير مقيّد)
    op.add_column("companies", sa.Column("license_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "license_until")
