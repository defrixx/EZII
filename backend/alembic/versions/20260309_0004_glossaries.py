"""add glossary sets and link entries

Revision ID: 20260309_0004
Revises: 20260309_0003
Create Date: 2026-03-09
"""

import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260309_0004"
down_revision = "20260309_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "glossaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_glossary_tenant_name"),
    )
    op.create_index("ix_glossaries_tenant_id", "glossaries", ["tenant_id"])

    op.add_column("glossary_entries", sa.Column("glossary_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_glossary_entries_glossary_id", "glossary_entries", ["glossary_id"])
    op.create_foreign_key(
        "fk_glossary_entries_glossary_id",
        "glossary_entries",
        "glossaries",
        ["glossary_id"],
        ["id"],
    )

    conn = op.get_bind()
    tenant_rows = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()
    now = datetime.utcnow()
    tenant_defaults: dict[str, str] = {}

    for row in tenant_rows:
        tenant_id = str(row.id)
        glossary_id = str(uuid.uuid4())
        tenant_defaults[tenant_id] = glossary_id
        conn.execute(
            sa.text(
                """
                INSERT INTO glossaries
                (id, tenant_id, name, description, priority, enabled, is_default, created_at, updated_at)
                VALUES
                (:id, :tenant_id, :name, :description, :priority, :enabled, :is_default, :created_at, :updated_at)
                """
            ),
            {
                "id": glossary_id,
                "tenant_id": tenant_id,
                "name": "Default",
                "description": "Auto-created default glossary",
                "priority": 100,
                "enabled": True,
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            },
        )

    if tenant_defaults:
        for tenant_id, glossary_id in tenant_defaults.items():
            conn.execute(
                sa.text(
                    """
                    UPDATE glossary_entries
                    SET glossary_id = :glossary_id
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"glossary_id": glossary_id, "tenant_id": tenant_id},
            )

    op.alter_column("glossary_entries", "glossary_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_glossary_entries_glossary_id", "glossary_entries", type_="foreignkey")
    op.drop_index("ix_glossary_entries_glossary_id", table_name="glossary_entries")
    op.drop_column("glossary_entries", "glossary_id")

    op.drop_index("ix_glossaries_tenant_id", table_name="glossaries")
    op.drop_table("glossaries")
