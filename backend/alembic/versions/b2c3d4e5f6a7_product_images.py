"""product images: image_url (رمز رابط) + image_blob/image_mime (ملف مرفوع)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-05 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column("products", sa.Column("image_blob", sa.LargeBinary(), nullable=True))
    op.add_column("products", sa.Column("image_mime", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "image_mime")
    op.drop_column("products", "image_blob")
    op.drop_column("products", "image_url")
