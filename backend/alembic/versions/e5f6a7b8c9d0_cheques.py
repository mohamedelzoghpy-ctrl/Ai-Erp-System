"""cheque portfolio (حافظة الشيكات): received/issued cheques with lifecycle statuses

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cheques',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(),
                  sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('direction', sa.String(length=10), nullable=False, index=True),  # received | issued
        sa.Column('number', sa.String(length=60), nullable=False),
        sa.Column('bank_id', sa.Integer(), sa.ForeignKey('banks.id'), nullable=False, index=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=True, index=True),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id'), nullable=True, index=True),
        sa.Column('cheque_date', sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='under_collection', index=True),
        sa.Column('payment_id', sa.Integer(), sa.ForeignKey('payments.id'), nullable=True, index=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('cheques')
