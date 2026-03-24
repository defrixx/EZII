"""add knowledge mode to provider settings and traces

Revision ID: 20260324_0009
Revises: 20260324_0008
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0009"
down_revision = "20260324_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_settings",
        sa.Column("knowledge_mode", sa.String(length=50), nullable=False, server_default=sa.text("'glossary_documents'")),
    )
    op.execute(
        """
        UPDATE provider_settings
        SET knowledge_mode = CASE
            WHEN web_enabled IS TRUE THEN 'glossary_documents_web'
            ELSE 'glossary_documents'
        END
        """
    )
    op.add_column(
        "response_traces",
        sa.Column("knowledge_mode", sa.String(length=50), nullable=False, server_default=sa.text("'glossary_documents'")),
    )


def downgrade() -> None:
    op.drop_column("response_traces", "knowledge_mode")
    op.drop_column("provider_settings", "knowledge_mode")
