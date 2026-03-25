"""add storage cleanup tasks queue table

Revision ID: 20260325_0018
Revises: 20260325_0017
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260325_0018"
down_revision = "20260325_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_cleanup_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "storage_path", name="uq_storage_cleanup_task_tenant_path"),
        sa.CheckConstraint("status IN ('pending', 'running', 'failed')", name="ck_storage_cleanup_tasks_status"),
    )
    op.create_index("ix_storage_cleanup_tasks_tenant_id", "storage_cleanup_tasks", ["tenant_id"])
    op.create_index("ix_storage_cleanup_tasks_status", "storage_cleanup_tasks", ["status"])
    op.create_index("ix_storage_cleanup_tasks_next_attempt_at", "storage_cleanup_tasks", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_storage_cleanup_tasks_next_attempt_at", table_name="storage_cleanup_tasks")
    op.drop_index("ix_storage_cleanup_tasks_status", table_name="storage_cleanup_tasks")
    op.drop_index("ix_storage_cleanup_tasks_tenant_id", table_name="storage_cleanup_tasks")
    op.drop_table("storage_cleanup_tasks")
