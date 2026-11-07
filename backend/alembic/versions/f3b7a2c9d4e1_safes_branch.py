"""associate each safe with a branch

Revision ID: f3b7a2c9d4e1
Revises: f2a8c9d1e3b4
Create Date: 2026-10-28 19:55:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b7a2c9d4e1"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("safes", sa.Column("branch_id", sa.Integer(), nullable=True))
    connection = op.get_bind()
    companies_without_branch = connection.execute(
        sa.text(
            "SELECT c.id, c.code FROM companies AS c "
            "WHERE NOT EXISTS (SELECT 1 FROM branches AS b WHERE b.company_id = c.id) "
            "ORDER BY c.id"
        )
    ).all()
    for company_id, company_code in companies_without_branch:
        branch_code = "main"
        suffix = 2
        while connection.execute(
            sa.text("SELECT 1 FROM branches WHERE company_id = :company_id AND code = :code"),
            {"company_id": company_id, "code": branch_code},
        ).first():
            branch_code = f"main-{suffix}"
            suffix += 1
        connection.execute(
            sa.text(
                "INSERT INTO branches (company_id, name, code, is_active, created_at, updated_at) "
                "VALUES (:company_id, :name, :code, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"company_id": company_id, "name": f"Main Branch ({company_code})", "code": branch_code},
        )

    connection.execute(
        sa.text(
            "UPDATE safes AS s SET branch_id = ("
            "SELECT b.id FROM branches AS b WHERE b.company_id = s.company_id "
            "ORDER BY b.id LIMIT 1)"
        )
    )
    with op.batch_alter_table("safes") as batch_op:
        batch_op.alter_column("branch_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_safes_branch_id_branches", "branches", ["branch_id"], ["id"], ondelete="RESTRICT"
        )
        batch_op.create_index("ix_safes_branch_id", ["branch_id"])


def downgrade() -> None:
    with op.batch_alter_table("safes") as batch_op:
        batch_op.drop_index("ix_safes_branch_id")
        batch_op.drop_constraint("fk_safes_branch_id_branches", type_="foreignkey")
        batch_op.drop_column("branch_id")
