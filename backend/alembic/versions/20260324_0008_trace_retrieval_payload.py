"""add retrieval payload fields to response traces

Revision ID: 20260324_0008
Revises: 20260324_0007
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260324_0008"
down_revision = "20260324_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "response_traces",
        sa.Column("source_types", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "response_traces",
        sa.Column("document_ids", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "response_traces",
        sa.Column("web_snapshot_ids", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("response_traces", "web_snapshot_ids")
    op.drop_column("response_traces", "document_ids")
    op.drop_column("response_traces", "source_types")
