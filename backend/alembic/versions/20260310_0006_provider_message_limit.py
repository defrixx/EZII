"""add max user messages total to provider settings

Revision ID: 20260310_0006
Revises: 20260309_0005
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260310_0006"
down_revision = "20260309_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_settings",
        sa.Column("max_user_messages_total", sa.Integer(), nullable=False, server_default=sa.text("5")),
    )


def downgrade() -> None:
    op.drop_column("provider_settings", "max_user_messages_total")
