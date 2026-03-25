"""drop allowlist domains

Revision ID: 20260325_0012
Revises: 20260325_0011
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260325_0012"
down_revision = "20260325_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_allowlist_domains_tenant_id", table_name="allowlist_domains")
    op.drop_table("allowlist_domains")


def downgrade() -> None:
    op.create_table(
        "allowlist_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "domain", name="uq_allowlist_tenant_domain"),
    )
    op.create_index("ix_allowlist_domains_tenant_id", "allowlist_domains", ["tenant_id"])
