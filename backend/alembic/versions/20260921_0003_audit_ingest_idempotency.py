"""add idempotency key for cross-domain audit ingestion

Revision ID: 20260921_0003
Revises: 20260921_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0003"
down_revision = "20260921_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_event", sa.Column("source_event_id", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_audit_source_event", "audit_event", ["source_event_id"])


def downgrade() -> None:
    op.drop_constraint("uq_audit_source_event", "audit_event", type_="unique")
    op.drop_column("audit_event", "source_event_id")
