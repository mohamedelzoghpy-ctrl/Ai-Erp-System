"""QC: إعادة الفحص — عمود attempt لنتائج القياسات + قيد فريد ب يشمل المحاولة.

Revision ID: qcm2026111303
Revises: crm2026111302
Create Date: 2026-11-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "qcm2026111303"
down_revision = "crm2026111302"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("batch_qc_results", sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("production_batches", sa.Column("qc_attempt", sa.Integer(), nullable=False, server_default="1"))
    op.drop_constraint("uq_batch_qc_result", "batch_qc_results", type_="unique")
    op.create_unique_constraint("uq_batch_qc_result_attempt", "batch_qc_results", ["batch_id", "attempt", "parameter_id"])


def downgrade() -> None:
    op.drop_column("production_batches", "qc_attempt")
    op.drop_constraint("uq_batch_qc_result_attempt", "batch_qc_results", type_="unique")
    op.create_unique_constraint("uq_batch_qc_result", "batch_qc_results", ["batch_id", "parameter_id"])
    op.drop_column("batch_qc_results", "attempt")
