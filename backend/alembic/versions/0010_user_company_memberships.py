"""user-company memberships

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_platform_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "user_company_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="staff", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'manager', 'staff')", name="ck_membership_role"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_company_membership"),
    )
    op.create_index("ix_user_company_memberships_id", "user_company_memberships", ["id"], unique=False)
    op.create_index("ix_user_company_memberships_user_id", "user_company_memberships", ["user_id"], unique=False)
    op.create_index("ix_user_company_memberships_company_id", "user_company_memberships", ["company_id"], unique=False)
    op.create_table(
        "user_branch_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "branch_id", name="uq_user_branch_access"),
    )
    op.create_index("ix_user_branch_access_id", "user_branch_access", ["id"], unique=False)
    op.create_index("ix_user_branch_access_user_id", "user_branch_access", ["user_id"], unique=False)
    op.create_index("ix_user_branch_access_branch_id", "user_branch_access", ["branch_id"], unique=False)
    op.create_table(
        "user_warehouse_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "warehouse_id", name="uq_user_warehouse_access"),
    )
    op.create_index("ix_user_warehouse_access_id", "user_warehouse_access", ["id"], unique=False)
    op.create_index("ix_user_warehouse_access_user_id", "user_warehouse_access", ["user_id"], unique=False)
    op.create_index(
        "ix_user_warehouse_access_warehouse_id", "user_warehouse_access", ["warehouse_id"], unique=False
    )

    op.execute(
        "INSERT INTO user_company_memberships (user_id, company_id, role) "
        "SELECT users.id, companies.id, users.role "
        "FROM users CROSS JOIN companies WHERE companies.code = 'default'"
    )
    op.execute(
        "INSERT INTO user_branch_access (user_id, branch_id) "
        "SELECT memberships.user_id, branches.id "
        "FROM user_company_memberships AS memberships "
        "JOIN branches ON branches.company_id = memberships.company_id"
    )
    op.execute(
        "INSERT INTO user_warehouse_access (user_id, warehouse_id) "
        "SELECT memberships.user_id, warehouses.id "
        "FROM user_company_memberships AS memberships "
        "JOIN branches ON branches.company_id = memberships.company_id "
        "JOIN warehouses ON warehouses.branch_id = branches.id"
    )
    op.execute(
        "UPDATE users SET is_platform_admin = TRUE "
        "WHERE id = (SELECT MIN(id) FROM users WHERE role = 'admin' AND is_active = TRUE)"
    )


def downgrade() -> None:
    op.drop_index("ix_user_warehouse_access_warehouse_id", table_name="user_warehouse_access")
    op.drop_index("ix_user_warehouse_access_user_id", table_name="user_warehouse_access")
    op.drop_index("ix_user_warehouse_access_id", table_name="user_warehouse_access")
    op.drop_table("user_warehouse_access")
    op.drop_index("ix_user_branch_access_branch_id", table_name="user_branch_access")
    op.drop_index("ix_user_branch_access_user_id", table_name="user_branch_access")
    op.drop_index("ix_user_branch_access_id", table_name="user_branch_access")
    op.drop_table("user_branch_access")
    op.drop_index("ix_user_company_memberships_company_id", table_name="user_company_memberships")
    op.drop_index("ix_user_company_memberships_user_id", table_name="user_company_memberships")
    op.drop_index("ix_user_company_memberships_id", table_name="user_company_memberships")
    op.drop_table("user_company_memberships")
    op.drop_column("users", "is_platform_admin")
