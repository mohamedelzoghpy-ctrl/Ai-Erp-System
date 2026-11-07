"""manufacturing phase 3: subcontracting + production line scheduling (تصنيع خارجي وجدولة)

Revision ID: i8j9k0l1m2n3
Revises: h7i9j0k1l2m3
Create Date: 2026-11-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'i8j9k0l1m2n3'
down_revision = 'h7i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'production_orders',
        sa.Column('subcontractor_id', sa.Integer(),
                  sa.ForeignKey('suppliers.id'), nullable=True, index=True),
    )
    op.add_column(
        'production_orders',
        sa.Column('production_line', sa.String(length=100), nullable=True),
    )


def downgrade():
    op.drop_column('production_orders', 'production_line')
    op.drop_column('production_orders', 'subcontractor_id')
