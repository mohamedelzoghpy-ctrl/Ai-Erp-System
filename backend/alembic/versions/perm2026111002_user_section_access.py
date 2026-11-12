"""Multi-section per user: user_section_access (union of section permissions)

Revision ID: perm2026111002
Revises: perm2026111001
Create Date: 2026-11-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "perm2026111002"
down_revision = "perm2026111001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # أقسام الصلاحيات المسندة للمستخدم — عدة أقسام لموظف واحد (اتحاد الصلاحيات)
    op.create_table(
        "user_section_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["access_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "user_id", "section_id", name="uq_user_section_access"),
    )
    op.create_index("ix_user_section_access_id", "user_section_access", ["id"])
    op.create_index("ix_user_section_access_company_id", "user_section_access", ["company_id"])
    op.create_index("ix_user_section_access_user_id", "user_section_access", ["user_id"])
    op.create_index("ix_user_section_access_section_id", "user_section_access", ["section_id"])

    # ترحيل الإسناد القديم (قسم واحد لكل عضوية) إلى الجدول الجديد — idempotent
    op.execute(
        """
        INSERT INTO user_section_access (company_id, user_id, section_id)
        SELECT DISTINCT m.company_id, m.user_id, m.section_id
        FROM user_company_memberships m
        WHERE m.section_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_section_access_section_id", table_name="user_section_access")
    op.drop_index("ix_user_section_access_user_id", table_name="user_section_access")
    op.drop_index("ix_user_section_access_company_id", table_name="user_section_access")
    op.drop_index("ix_user_section_access_id", table_name="user_section_access")
    op.drop_table("user_section_access")
