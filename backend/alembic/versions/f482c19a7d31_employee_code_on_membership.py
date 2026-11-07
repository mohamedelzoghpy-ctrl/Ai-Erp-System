"""store generated employee codes on company memberships

Revision ID: f482c19a7d31
Revises: ef16b42a9c70
Create Date: 2026-11-02 11:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f482c19a7d31"
down_revision = "ef16b42a9c70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_company_memberships", sa.Column("employee_code", sa.String(length=60), nullable=True))
    op.create_index("ix_user_company_memberships_employee_code", "user_company_memberships", ["company_id", "employee_code"], unique=True)
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT id, company_id, user_id FROM user_company_memberships ORDER BY company_id, id"
    )).all()
    counters = {}
    for membership_id, company_id, user_id in rows:
        counters[company_id] = counters.get(company_id, 0) + 1
        connection.execute(
            sa.text("UPDATE user_company_memberships SET employee_code = :code WHERE id = :id"),
            {"code": str(counters[company_id]), "id": membership_id},
        )


def downgrade() -> None:
    op.drop_index("ix_user_company_memberships_employee_code", table_name="user_company_memberships")
    op.drop_column("user_company_memberships", "employee_code")
