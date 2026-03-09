"""enforce single default glossary per tenant

Revision ID: 20260309_0005
Revises: 20260309_0004
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260309_0005"
down_revision = "20260309_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep only one default glossary per tenant before adding unique partial index.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
              SELECT id,
                     tenant_id,
                     is_default,
                     ROW_NUMBER() OVER (
                       PARTITION BY tenant_id
                       ORDER BY is_default DESC, created_at ASC, id ASC
                     ) AS rn
              FROM glossaries
            )
            UPDATE glossaries g
            SET is_default = CASE WHEN ranked.rn = 1 THEN TRUE ELSE FALSE END
            FROM ranked
            WHERE g.id = ranked.id
            """
        )
    )

    op.create_index(
        "uq_glossary_single_default_per_tenant",
        "glossaries",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_glossary_single_default_per_tenant", table_name="glossaries")
