"""add indexes for document metadata filters

Revision ID: 20260325_0017
Revises: 20260325_0016
Create Date: 2026-03-25
"""

from alembic import op


revision = "20260325_0017"
down_revision = "20260325_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_documents_tenant_source_status_updated",
        "documents",
        ["tenant_id", "source_type", "status", "updated_at"],
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_metadata_jsonb_gin ON documents USING gin ((metadata_json::jsonb))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_metadata_jsonb_gin")
    op.drop_index("ix_documents_tenant_source_status_updated", table_name="documents")
