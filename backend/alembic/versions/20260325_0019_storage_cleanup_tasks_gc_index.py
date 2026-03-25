"""add index for storage cleanup failed-task GC

Revision ID: 20260325_0019
Revises: 20260325_0018
Create Date: 2026-03-25
"""

from alembic import op


revision = "20260325_0019"
down_revision = "20260325_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_storage_cleanup_tasks_status_updated_at",
        "storage_cleanup_tasks",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_storage_cleanup_tasks_status_updated_at", table_name="storage_cleanup_tasks")
