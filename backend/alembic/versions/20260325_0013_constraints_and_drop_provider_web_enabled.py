"""add DB check constraints and drop provider web_enabled

Revision ID: 20260325_0013
Revises: 20260325_0011
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0013"
down_revision = "20260325_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    table_names = set(inspector.get_table_names())
    if "provider_settings" in table_names:
        provider_columns = {column["name"] for column in inspector.get_columns("provider_settings")}
        if "web_enabled" in provider_columns:
            op.drop_column("provider_settings", "web_enabled")

    op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'user')")
    op.create_check_constraint("ck_messages_role", "messages", "role IN ('user', 'assistant')")
    op.create_check_constraint(
        "ck_glossary_entries_status",
        "glossary_entries",
        "status IN ('active', 'draft', 'disabled', 'archived')",
    )
    op.create_check_constraint(
        "ck_documents_source_type",
        "documents",
        "source_type IN ('upload', 'website_snapshot')",
    )
    op.create_check_constraint(
        "ck_documents_status",
        "documents",
        "status IN ('draft', 'processing', 'approved', 'archived', 'failed')",
    )
    op.create_check_constraint(
        "ck_document_ingestion_jobs_status",
        "document_ingestion_jobs",
        "status IN ('pending', 'running', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_provider_settings_knowledge_mode",
        "provider_settings",
        "knowledge_mode IN ('glossary_only', 'glossary_documents', 'glossary_documents_web')",
    )
    op.create_check_constraint(
        "ck_provider_settings_empty_retrieval_mode",
        "provider_settings",
        "empty_retrieval_mode IN ('strict_fallback', 'model_only_fallback', 'clarifying_fallback')",
    )
    op.create_check_constraint(
        "ck_provider_settings_response_tone",
        "provider_settings",
        "response_tone IN ('consultative_supportive', 'neutral_reference')",
    )
    op.create_check_constraint(
        "ck_response_traces_knowledge_mode",
        "response_traces",
        "knowledge_mode IN ('glossary_only', 'glossary_documents', 'glossary_documents_web')",
    )
    op.create_check_constraint(
        "ck_response_traces_answer_mode",
        "response_traces",
        "answer_mode IN ('grounded', 'strict_fallback', 'model_only', 'clarifying', 'error')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_response_traces_answer_mode", "response_traces", type_="check")
    op.drop_constraint("ck_response_traces_knowledge_mode", "response_traces", type_="check")
    op.drop_constraint("ck_provider_settings_response_tone", "provider_settings", type_="check")
    op.drop_constraint("ck_provider_settings_empty_retrieval_mode", "provider_settings", type_="check")
    op.drop_constraint("ck_provider_settings_knowledge_mode", "provider_settings", type_="check")
    op.drop_constraint("ck_document_ingestion_jobs_status", "document_ingestion_jobs", type_="check")
    op.drop_constraint("ck_documents_status", "documents", type_="check")
    op.drop_constraint("ck_documents_source_type", "documents", type_="check")
    op.drop_constraint("ck_glossary_entries_status", "glossary_entries", type_="check")
    op.drop_constraint("ck_messages_role", "messages", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "provider_settings" in table_names:
        provider_columns = {column["name"] for column in inspector.get_columns("provider_settings")}
        if "web_enabled" not in provider_columns:
            op.add_column(
                "provider_settings",
                sa.Column("web_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            )
            op.alter_column("provider_settings", "web_enabled", server_default=None)
