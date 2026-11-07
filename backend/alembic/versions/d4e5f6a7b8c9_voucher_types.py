"""voucher types: party-less receipts/payments via category requires_party + stored kind

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # Allow vouchers with no party at all (general income / general expense),
    # still forbid having both a customer and a supplier.
    op.drop_constraint("ck_payment_one_party", "payments", type_="check")
    op.create_check_constraint(
        "ck_payment_party_shape",
        "payments",
        "NOT (customer_id IS NOT NULL AND supplier_id IS NOT NULL)",
    )
    # Stored discriminator: existing rows are receipts when they have a customer.
    op.add_column(
        "payments",
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="receipt", index=True),
    )
    op.execute("UPDATE payments SET kind = 'payment' WHERE customer_id IS NULL")
    op.add_column(
        "payment_categories",
        sa.Column("requires_party", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade():
    op.drop_column("payment_categories", "requires_party")
    op.drop_constraint("ck_payment_party_shape", "payments", type_="check")
    op.create_check_constraint(
        "ck_payment_one_party",
        "payments",
        "(customer_id IS NOT NULL) <> (supplier_id IS NOT NULL)",
    )
    # Party-less rows cannot survive the old constraint.
    op.execute("DELETE FROM payments WHERE customer_id IS NULL AND supplier_id IS NULL")
    op.drop_column("payments", "kind")
