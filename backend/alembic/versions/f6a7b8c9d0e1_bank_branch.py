"""bank branch link (ربط البنك بفرع أو الشركة ككل)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "banks",
        sa.Column("branch_id", sa.Integer(),
                  sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True, index=True),
    )


def downgrade():
    op.drop_column("banks", "branch_id")
