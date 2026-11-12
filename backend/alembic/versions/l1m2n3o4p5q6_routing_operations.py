"""مراحل التشغيل (Routing & Operations): مراكز التشغيل + مسار قائمة المواد + مراحل أمر التصنيع

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-11-08

- work_centers: مراكز التشغيل (قدرة/تكلفة الساعة)
- bom_operations: مسار التشغيل لكل قائمة مواد (مراحل مرتبة بـ seq)
- bom_items.operation_seq: ربط كل مكوّن بمرحلة صرفه
- production_order_operations: snapshot المراحل على أمر التشغيل مع التقدم المرحلي
- قيد فريد (order_id, batch_no) على الدفعات لمنع التسجيل المزدوج
"""
from alembic import op
import sqlalchemy as sa

revision = "l1m2n3o4p5q6"
down_revision = "k0l1m2n3o4p5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_centers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("capacity_per_hour", sa.Numeric(12, 3), nullable=True),
        sa.Column("hourly_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "name", name="uq_work_center_company_name"),
    )
    op.create_table(
        "bom_operations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("bom_id", sa.Integer(), sa.ForeignKey("boms.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("work_center_id", sa.Integer(), sa.ForeignKey("work_centers.id"), nullable=True, index=True),
        sa.Column("run_minutes_per_unit", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(200), nullable=True),
        sa.UniqueConstraint("bom_id", "seq", name="uq_bom_operation_seq"),
    )
    op.create_table(
        "production_order_operations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("work_center_id", sa.Integer(), sa.ForeignKey("work_centers.id"), nullable=True, index=True),
        sa.Column("run_minutes_per_unit", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("qty_done", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("qty_scrapped", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("issued", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_id", "seq", name="uq_poo_order_seq"),
    )
    op.add_column("bom_items", sa.Column("operation_seq", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_production_batch_no", "production_batches", ["order_id", "batch_no"])


def downgrade() -> None:
    op.drop_constraint("uq_production_batch_no", "production_batches", type_="unique")
    op.drop_column("bom_items", "operation_seq")
    op.drop_table("production_order_operations")
    op.drop_table("bom_operations")
    op.drop_table("work_centers")
