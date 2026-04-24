"""add github playbook knowledge mode

Revision ID: 20260424_0022
Revises: 20260424_0021
Create Date: 2026-04-24
"""

from alembic import op


revision = "20260424_0022"
down_revision = "20260424_0021"
branch_labels = None
depends_on = None


NEW_MODES = "('glossary_only', 'glossary_documents', 'glossary_documents_web', 'glossary_github_documents_web')"
OLD_MODES = "('glossary_only', 'glossary_documents', 'glossary_documents_web')"


def upgrade() -> None:
    op.drop_constraint("ck_provider_settings_knowledge_mode", "provider_settings", type_="check")
    op.create_check_constraint(
        "ck_provider_settings_knowledge_mode",
        "provider_settings",
        f"knowledge_mode IN {NEW_MODES}",
    )
    op.drop_constraint("ck_response_traces_knowledge_mode", "response_traces", type_="check")
    op.create_check_constraint(
        "ck_response_traces_knowledge_mode",
        "response_traces",
        f"knowledge_mode IN {NEW_MODES}",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE provider_settings SET knowledge_mode = 'glossary_documents_web' "
        "WHERE knowledge_mode = 'glossary_github_documents_web'"
    )
    op.execute(
        "UPDATE response_traces SET knowledge_mode = 'glossary_documents_web' "
        "WHERE knowledge_mode = 'glossary_github_documents_web'"
    )
    op.drop_constraint("ck_response_traces_knowledge_mode", "response_traces", type_="check")
    op.create_check_constraint(
        "ck_response_traces_knowledge_mode",
        "response_traces",
        f"knowledge_mode IN {OLD_MODES}",
    )
    op.drop_constraint("ck_provider_settings_knowledge_mode", "provider_settings", type_="check")
    op.create_check_constraint(
        "ck_provider_settings_knowledge_mode",
        "provider_settings",
        f"knowledge_mode IN {OLD_MODES}",
    )
