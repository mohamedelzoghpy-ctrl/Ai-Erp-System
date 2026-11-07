"""payment categories for receipts/payments (بنود القبض والصرف)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False, server_default='receipt', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('company_id', 'kind', 'name', name='uq_payment_category_name'),
    )
    op.add_column(
        'payments',
        sa.Column('category_id', sa.Integer(),
                  sa.ForeignKey('payment_categories.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade():
    op.drop_column('payments', 'category_id')
    op.drop_table('payment_categories')
