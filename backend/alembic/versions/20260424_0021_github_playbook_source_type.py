"""add github playbook document source type

Revision ID: 20260424_0021
Revises: 20260329_0020
Create Date: 2026-04-24
"""

from alembic import op


revision = "20260424_0021"
down_revision = "20260329_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_documents_source_type", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_type",
        "documents",
        "source_type IN ('upload', 'website_snapshot', 'github_playbook')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_source_type", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_type",
        "documents",
        "source_type IN ('upload', 'website_snapshot')",
    )
