"""enforce case-insensitive glossary term uniqueness per glossary

Revision ID: 20260325_0014
Revises: 20260325_0013
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0014"
down_revision = "20260325_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM glossary_entries ge
            USING (
              SELECT id
              FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                         PARTITION BY tenant_id, glossary_id, lower(term)
                         ORDER BY created_at ASC, id ASC
                       ) AS rn
                FROM glossary_entries
              ) ranked
              WHERE ranked.rn > 1
            ) dupes
            WHERE ge.id = dupes.id
            """
        )
    )
    op.create_index(
        "uq_glossary_entries_tenant_glossary_term_ci",
        "glossary_entries",
        ["tenant_id", "glossary_id", sa.text("lower(term)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_glossary_entries_tenant_glossary_term_ci", table_name="glossary_entries")

