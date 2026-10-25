"""company and branch foundation

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("max_warehouses_per_branch", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "max_warehouses_per_branch IS NULL OR max_warehouses_per_branch > 0",
            name="ck_company_warehouse_limit_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("companies") as batch_op:
        batch_op.create_index("ix_companies_id", ["id"], unique=False)
        batch_op.create_index("ix_companies_code", ["code"], unique=True)

    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_branch_company_code"),
    )
    with op.batch_alter_table("branches") as batch_op:
        batch_op.create_index("ix_branches_id", ["id"], unique=False)
        batch_op.create_index("ix_branches_company_id", ["company_id"], unique=False)

    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_warehouses_branch_id_branches",
            "branches",
            ["branch_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO companies (name, code, max_warehouses_per_branch) "
            "VALUES (:name, :code, NULL)"
        ),
        {"name": "Default Company", "code": "default"},
    )
    company_id = connection.execute(
        sa.text("SELECT id FROM companies WHERE code = :code"), {"code": "default"}
    ).scalar_one()
    connection.execute(
        sa.text(
            "INSERT INTO branches (company_id, name, code) "
            "VALUES (:company_id, :name, :code)"
        ),
        {"company_id": company_id, "name": "Main Branch", "code": "main"},
    )
    branch_id = connection.execute(
        sa.text(
            "SELECT id FROM branches WHERE company_id = :company_id AND code = :code"
        ),
        {"company_id": company_id, "code": "main"},
    ).scalar_one()
    connection.execute(
        sa.text("UPDATE warehouses SET branch_id = :branch_id WHERE branch_id IS NULL"),
        {"branch_id": branch_id},
    )

    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.alter_column(
            "branch_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_index("ix_warehouses_branch_id", ["branch_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("warehouses") as batch_op:
        batch_op.drop_index("ix_warehouses_branch_id")
        batch_op.drop_constraint("fk_warehouses_branch_id_branches", type_="foreignkey")
        batch_op.drop_column("branch_id")

    with op.batch_alter_table("branches") as batch_op:
        batch_op.drop_index("ix_branches_company_id")
        batch_op.drop_index("ix_branches_id")
    op.drop_table("branches")

    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_index("ix_companies_code")
        batch_op.drop_index("ix_companies_id")
    op.drop_table("companies")
