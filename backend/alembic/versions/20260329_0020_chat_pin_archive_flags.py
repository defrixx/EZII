"""add chat pin/archive flags

Revision ID: 20260329_0020
Revises: 20260325_0019
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260329_0020"
down_revision = "20260325_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("chats", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_chats_is_pinned", "chats", ["is_pinned"], unique=False)
    op.create_index("ix_chats_is_archived", "chats", ["is_archived"], unique=False)
    op.alter_column("chats", "is_pinned", server_default=None)
    op.alter_column("chats", "is_archived", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_chats_is_archived", table_name="chats")
    op.drop_index("ix_chats_is_pinned", table_name="chats")
    op.drop_column("chats", "is_archived")
    op.drop_column("chats", "is_pinned")

