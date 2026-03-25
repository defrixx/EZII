"""drop unused allowlist_domains_legacy table (no-op)

Revision ID: 20260325_0016
Revises: 20260325_0015
Create Date: 2026-03-25
"""


revision = "20260325_0016"
down_revision = "20260325_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy allowlist table is intentionally ignored in current schema history.
    return None


def downgrade() -> None:
    return None
