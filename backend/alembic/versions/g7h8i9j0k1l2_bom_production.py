"""manufacturing phase 1: BOMs + production orders with consumptions (التصنيع)

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g7h8i9j0k1l2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'boms',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('version', sa.String(length=20), nullable=False, server_default='v1'),
        sa.Column('output_qty', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('company_id', 'product_id', 'version', name='uq_bom_product_version'),
    )
    op.create_table(
        'bom_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('boms.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('component_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('qty_per_output', sa.Numeric(12, 3), nullable=False),
        sa.Column('scrap_pct', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('notes', sa.String(length=200), nullable=True),
        sa.UniqueConstraint('bom_id', 'component_id', name='uq_bom_component'),
    )
    op.create_table(
        'production_orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('code', sa.String(length=50), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('boms.id'), nullable=True, index=True),
        sa.Column('qty_planned', sa.Integer(), nullable=False),
        sa.Column('qty_produced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft', index=True),
        sa.Column('raw_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('output_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('company_id', 'code', name='uq_production_order_company_code'),
    )
    op.create_table(
        'production_consumptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(),
                  sa.ForeignKey('production_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('component_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('unit_cost', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.UniqueConstraint('order_id', 'component_id', name='uq_production_consumption'),
    )


def downgrade():
    op.drop_table('production_consumptions')
    op.drop_table('production_orders')
    op.drop_table('bom_items')
    op.drop_table('boms')
