"""Permission system: global catalog, access sections, per-user overrides

Revision ID: perm2026111001
Revises: hr2026110906
Create Date: 2026-11-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "perm2026111001"
down_revision = "m0n1o2p3q4r5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # كتالوج الصلاحيات (عالمي — غير tenant-scoped)
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("module", sa.String(length=60), nullable=False),
        sa.Column("resource", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("is_dangerous", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_field", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_permission_code"),
    )
    op.create_index("ix_permissions_id", "permissions", ["id"])
    op.create_index("ix_permissions_code", "permissions", ["code"])
    op.create_index("ix_permissions_module", "permissions", ["module"])
    op.create_index("ix_permissions_resource", "permissions", ["resource"])

    # أقسام الصلاحيات (tenant-scoped)
    op.create_table(
        "access_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_access_section_code"),
    )
    op.create_index("ix_access_sections_id", "access_sections", ["id"])
    op.create_index("ix_access_sections_company_id", "access_sections", ["company_id"])
    op.create_index("ix_access_sections_code", "access_sections", ["code"])

    # مصفوفة القسم × الصلاحية
    op.create_table(
        "access_section_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["section_id"], ["access_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "permission_id", name="uq_section_permission"),
    )
    op.create_index("ix_access_section_permissions_id", "access_section_permissions", ["id"])
    op.create_index("ix_access_section_permissions_company_id", "access_section_permissions", ["company_id"])
    op.create_index("ix_access_section_permissions_section_id", "access_section_permissions", ["section_id"])
    op.create_index("ix_access_section_permissions_permission_id", "access_section_permissions", ["permission_id"])

    # الاستثناءات الفردية (grant / deny)
    op.create_table(
        "user_permission_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.Column("effect", sa.String(length=10), nullable=False, server_default="grant"),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("effect IN ('grant', 'deny')", name="ck_permission_override_effect"),
        sa.UniqueConstraint("user_id", "permission_id", name="uq_user_permission_override"),
    )
    op.create_index("ix_user_permission_overrides_id", "user_permission_overrides", ["id"])
    op.create_index("ix_user_permission_overrides_company_id", "user_permission_overrides", ["company_id"])
    op.create_index("ix_user_permission_overrides_user_id", "user_permission_overrides", ["user_id"])
    op.create_index("ix_user_permission_overrides_permission_id", "user_permission_overrides", ["permission_id"])

    # القسم الأساسي على العضوية
    op.add_column(
        "user_company_memberships",
        sa.Column(
            "section_id",
            sa.Integer(),
            sa.ForeignKey("access_sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_user_company_memberships_section_id", "user_company_memberships", ["section_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_company_memberships_section_id", table_name="user_company_memberships")
    op.drop_column("user_company_memberships", "section_id")
    op.drop_table("user_permission_overrides")
    op.drop_table("access_section_permissions")
    op.drop_table("access_sections")
    op.drop_table("permissions")
