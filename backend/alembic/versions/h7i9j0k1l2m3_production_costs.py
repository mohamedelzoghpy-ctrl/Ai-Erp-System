"""manufacturing phase 2: labor/overhead costs on production orders (أجور وأعباء التصنيع)

Revision ID: h7i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-11-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'h7i9j0k1l2m3'
down_revision = 'g7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'production_costs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(),
                  sa.ForeignKey('production_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('cost_type', sa.String(length=20), nullable=False, index=True),  # labor | overhead
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('production_costs')
