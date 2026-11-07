"""add per-company branch limit

Revision ID: a48c7f2d9b31
Revises: f3b7a2c9d4e1
Create Date: 2026-10-28 20:15:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a48c7f2d9b31"
down_revision = "f3b7a2c9d4e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("max_branches", sa.Integer(), nullable=True))
    with op.batch_alter_table("companies") as batch_op:
        batch_op.create_check_constraint(
            "ck_company_branch_limit_positive",
            "max_branches IS NULL OR max_branches > 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_constraint("ck_company_branch_limit_positive", type_="check")
        batch_op.drop_column("max_branches")
