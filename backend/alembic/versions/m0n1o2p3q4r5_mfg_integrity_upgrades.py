"""manufacturing integrity upgrades: BOM item snapshots on orders, scrap cost tracking, std unit cost (ترقيات سلامة التصنيع)

Revision ID: m0n1o2p3q4r5
Revises: hr2026110906
Create Date: 2026-11-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'm0n1o2p3q4r5'
down_revision = 'hr2026110906'
branch_labels = None
depends_on = None


def upgrade():
    # 1) جدول نسخ بنود قائمة المواد على أمر التشغيل (snapshot عند الإنشاء)
    op.create_table(
        'production_order_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(),
                  sa.ForeignKey('production_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('component_id', sa.Integer(),
                  sa.ForeignKey('products.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('qty_per_output', sa.Numeric(12, 3), nullable=False),
        sa.Column('scrap_pct', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('operation_seq', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=200), nullable=True),
        sa.UniqueConstraint('order_id', 'component_id', name='uq_poi_order_component'),
    )

    # 2) أعمدة جديدة على أوامر التصنيع
    op.add_column('production_orders',
                  sa.Column('scrap_cost', sa.Numeric(14, 2), nullable=False, server_default='0'))
    op.add_column('production_orders',
                  sa.Column('std_unit_cost', sa.Numeric(14, 4), nullable=True))

    # 3) تكلفة الهالك الحالية للأوامر الموجودة: أعد بناءها من قيود الهالك المرحّلة (WIP legs)
    #    القيود ذات المرجع = رقم الأمر وبها حساب WIP دائن = هالك؛ نستنتج مبلغ الهالك من أسعار الخامات؟
    #    الأبسط والأدق: الهالك القديم كان يُرحَّل إلى 5600 بقيمة unit_cost×qty — لا يمكن استرجاعها
    #    من القيود إلا بقراءة سطور 5600 المدينة المرتبطة برقم الأمر، لكن القيود لا تحمل order_id.
    #    الأوامر القديمة المكتملة أرصدتها صفرية، والأوامر المفتوحة القديمة نادرة — نتركها صفرًا:
    #    قيد الإغلاق الجديد سيصحح الرصيد تلقائيًا عند أول إنهاء (فروق = رصيد WIP المتبقي فعليًا).


def downgrade():
    op.drop_column('production_orders', 'std_unit_cost')
    op.drop_column('production_orders', 'scrap_cost')
    op.drop_table('production_order_items')
