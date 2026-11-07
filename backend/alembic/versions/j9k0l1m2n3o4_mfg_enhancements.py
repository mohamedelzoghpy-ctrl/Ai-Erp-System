"""manufacturing enhancements: scrap, batches, QC, production lines, child MOs (تحسينات التصنيع)

Revision ID: j9k0l1m2n3o4
Revises: i8j9k0l1m2n3
Create Date: 2026-11-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'j9k0l1m2n3o4'
down_revision = 'i8j9k0l1m2n3'
branch_labels = None
depends_on = None


def upgrade():
    # 1) خطوط الإنتاج (الجدول المرجعي أولًا)
    op.create_table(
        'production_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('capacity_per_hour', sa.Integer(), nullable=True),
        sa.Column('hourly_cost', sa.Numeric(14, 2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('company_id', 'name', name='uq_production_line_company_name'),
    )
    # 2) أعمدة أوامر التصنيع الجديدة
    op.add_column(
        'production_orders',
        sa.Column('qty_scrapped', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'production_orders',
        sa.Column('parent_order_id', sa.Integer(),
                  sa.ForeignKey('production_orders.id'), nullable=True, index=True),
    )
    op.add_column(
        'production_orders',
        sa.Column('production_line_id', sa.Integer(),
                  sa.ForeignKey('production_lines.id'), nullable=True),
    )
    op.drop_column('production_orders', 'production_line')
    # 3) دفعات الإنتاج
    op.create_table(
        'production_batches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(),
                  sa.ForeignKey('production_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('batch_no', sa.String(length=50), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('cost', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('qc_status', sa.String(length=20), nullable=False, server_default='pending', index=True),
        sa.Column('produced_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('notes', sa.String(length=200), nullable=True),
    )


def downgrade():
    op.drop_table('production_batches')
    op.drop_column('production_orders', 'production_line_id')
    op.add_column(
        'production_orders',
        sa.Column('production_line', sa.String(length=100), nullable=True),
    )
    op.drop_column('production_orders', 'parent_order_id')
    op.drop_column('production_orders', 'qty_scrapped')
    op.drop_table('production_lines')
