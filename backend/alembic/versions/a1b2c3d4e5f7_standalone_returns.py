"""standalone returns: order/party no longer mandatory on returns

Revision ID: a1b2c3d4e5f7
Revises: c9e0f1a2b3c4
Create Date: 2026-11-01 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f7'
down_revision = 'c9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sales_returns") as batch:
        batch.alter_column("order_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("customer_id", existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("purchase_returns") as batch:
        batch.alter_column("order_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("supplier_id", existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("sales_return_items") as batch:
        batch.alter_column("order_item_id", existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("purchase_return_items") as batch:
        batch.alter_column("order_item_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("sales_return_items") as batch:
        batch.alter_column("order_item_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("purchase_return_items") as batch:
        batch.alter_column("order_item_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("sales_returns") as batch:
        batch.alter_column("customer_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("order_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("purchase_returns") as batch:
        batch.alter_column("supplier_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("order_id", existing_type=sa.Integer(), nullable=False)
