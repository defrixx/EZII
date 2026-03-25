"""add chat context provider settings

Revision ID: 20260325_0011
Revises: 20260324_0010
Create Date: 2026-03-25 10:25:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0011"
down_revision = "20260324_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_settings",
        sa.Column("chat_context_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "provider_settings",
        sa.Column("history_user_turn_limit", sa.Integer(), nullable=False, server_default=sa.text("6")),
    )
    op.add_column(
        "provider_settings",
        sa.Column("history_message_limit", sa.Integer(), nullable=False, server_default=sa.text("12")),
    )
    op.add_column(
        "provider_settings",
        sa.Column("history_token_budget", sa.Integer(), nullable=False, server_default=sa.text("1200")),
    )
    op.add_column(
        "provider_settings",
        sa.Column("rewrite_history_message_limit", sa.Integer(), nullable=False, server_default=sa.text("8")),
    )

    op.alter_column("provider_settings", "chat_context_enabled", server_default=None)
    op.alter_column("provider_settings", "history_user_turn_limit", server_default=None)
    op.alter_column("provider_settings", "history_message_limit", server_default=None)
    op.alter_column("provider_settings", "history_token_budget", server_default=None)
    op.alter_column("provider_settings", "rewrite_history_message_limit", server_default=None)


def downgrade() -> None:
    op.drop_column("provider_settings", "rewrite_history_message_limit")
    op.drop_column("provider_settings", "history_token_budget")
    op.drop_column("provider_settings", "history_message_limit")
    op.drop_column("provider_settings", "history_user_turn_limit")
    op.drop_column("provider_settings", "chat_context_enabled")
