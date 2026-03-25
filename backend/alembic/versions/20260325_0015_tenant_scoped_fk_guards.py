"""add tenant-scoped foreign key guards

Revision ID: 20260325_0015
Revises: 20260325_0014
Create Date: 2026-03-25
"""

from alembic import op


revision = "20260325_0015"
down_revision = "20260325_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_users_tenant_id_id", "users", ["tenant_id", "id"])
    op.create_unique_constraint("uq_chats_tenant_id_id", "chats", ["tenant_id", "id"])
    op.create_unique_constraint("uq_documents_tenant_id_id", "documents", ["tenant_id", "id"])

    op.create_foreign_key(
        "fk_messages_tenant_chat",
        "messages",
        "chats",
        ["tenant_id", "chat_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_messages_tenant_user",
        "messages",
        "users",
        ["tenant_id", "user_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_document_chunks_tenant_document",
        "document_chunks",
        "documents",
        ["tenant_id", "document_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_document_jobs_tenant_document",
        "document_ingestion_jobs",
        "documents",
        ["tenant_id", "document_id"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_document_jobs_tenant_document", "document_ingestion_jobs", type_="foreignkey")
    op.drop_constraint("fk_document_chunks_tenant_document", "document_chunks", type_="foreignkey")
    op.drop_constraint("fk_messages_tenant_user", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_tenant_chat", "messages", type_="foreignkey")

    op.drop_constraint("uq_documents_tenant_id_id", "documents", type_="unique")
    op.drop_constraint("uq_chats_tenant_id_id", "chats", type_="unique")
    op.drop_constraint("uq_users_tenant_id_id", "users", type_="unique")
