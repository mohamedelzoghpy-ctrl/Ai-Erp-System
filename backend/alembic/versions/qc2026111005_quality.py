"""Quality checkpoints: qc_templates + qc_parameters + qc_product_requirements + batch_qc_results

Revision ID: qc2026111005
Revises: lot2026111004
Create Date: 2026-11-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "qc2026111005"
down_revision = "lot2026111004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qc_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_qc_template_name"),
    )
    op.create_index("ix_qc_templates_id", "qc_templates", ["id"])
    op.create_index("ix_qc_templates_company_id", "qc_templates", ["company_id"])

    op.create_table(
        "qc_parameters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("param_type", sa.String(length=10), nullable=False, server_default="number"),
        sa.Column("min_value", sa.Numeric(12, 3), nullable=True),
        sa.Column("max_value", sa.Numeric(12, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["qc_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "name", name="uq_qc_parameter_name"),
    )
    op.create_index("ix_qc_parameters_id", "qc_parameters", ["id"])
    op.create_index("ix_qc_parameters_template_id", "qc_parameters", ["template_id"])
    op.create_index("ix_qc_parameters_company_id", "qc_parameters", ["company_id"])

    op.create_table(
        "qc_product_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["qc_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "product_id", "template_id", name="uq_qc_product_template"),
    )
    op.create_index("ix_qc_product_requirements_id", "qc_product_requirements", ["id"])
    op.create_index("ix_qc_product_requirements_product_id", "qc_product_requirements", ["product_id"])
    op.create_index("ix_qc_product_requirements_template_id", "qc_product_requirements", ["template_id"])

    op.create_table(
        "batch_qc_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=True),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("parameter_name", sa.String(length=150), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("value_num", sa.Numeric(12, 3), nullable=True),
        sa.Column("value_text", sa.String(length=200), nullable=True),
        sa.Column("pass_fail", sa.Boolean(), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["production_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parameter_id"], ["qc_parameters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["qc_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "parameter_id", name="uq_batch_qc_result"),
    )
    op.create_index("ix_batch_qc_results_id", "batch_qc_results", ["id"])
    op.create_index("ix_batch_qc_results_batch_id", "batch_qc_results", ["batch_id"])
    op.create_index("ix_batch_qc_results_parameter_id", "batch_qc_results", ["parameter_id"])
    op.create_index("ix_batch_qc_results_company_id", "batch_qc_results", ["company_id"])


def downgrade() -> None:
    op.drop_table("batch_qc_results")
    op.drop_table("qc_product_requirements")
    op.drop_table("qc_parameters")
    op.drop_table("qc_templates")
