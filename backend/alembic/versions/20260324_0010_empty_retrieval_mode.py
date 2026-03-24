"""add empty retrieval mode and trace answer mode

Revision ID: 20260324_0010
Revises: 20260324_0009
Create Date: 2026-03-24 22:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0010"
down_revision = "20260324_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_settings",
        sa.Column(
            "empty_retrieval_mode",
            sa.String(length=50),
            nullable=False,
            server_default="model_only_fallback",
        ),
    )
    op.add_column(
        "response_traces",
        sa.Column(
            "answer_mode",
            sa.String(length=50),
            nullable=False,
            server_default="grounded",
        ),
    )
    op.execute(
        """
        UPDATE provider_settings
        SET empty_retrieval_mode = 'model_only_fallback'
        WHERE empty_retrieval_mode IS NULL OR empty_retrieval_mode = ''
        """
    )
    op.execute(
        """
        UPDATE response_traces
        SET answer_mode = CASE
            WHEN status = 'fallback' THEN 'strict_fallback'
            WHEN status = 'error' THEN 'error'
            ELSE 'grounded'
        END
        WHERE answer_mode IS NULL OR answer_mode = ''
        """
    )
    op.alter_column("provider_settings", "empty_retrieval_mode", server_default=None)
    op.alter_column("response_traces", "answer_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("response_traces", "answer_mode")
    op.drop_column("provider_settings", "empty_retrieval_mode")
