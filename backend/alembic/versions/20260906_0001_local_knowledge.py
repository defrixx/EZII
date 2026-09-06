"""local knowledge system initial schema

Revision ID: 20260906_0001
Revises:
"""
from alembic import op
from app.db.base import Base
import app.models.models  # noqa: F401

revision="20260906_0001"; down_revision=None; branch_labels=None; depends_on=None
def upgrade(): Base.metadata.create_all(bind=op.get_bind())
def downgrade(): Base.metadata.drop_all(bind=op.get_bind())
