"""create shared foundation tables

Revision ID: 20260921_0001
Revises:
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_object",
        sa.Column("file_id", sa.String(36), primary_key=True),
        sa.Column("storage_provider", sa.String(32), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("storage_provider", "bucket", "object_key", name="uq_file_object_location"),
        sa.UniqueConstraint("sha256", "size_bytes", name="uq_file_object_content"),
    )
    op.create_table(
        "domain_event_outbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_type", "idempotency_key", name="uq_outbox_event_idempotency"),
    )
    op.create_index("ix_outbox_unpublished", "domain_event_outbox", ["published_at", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="domain_event_outbox")
    op.drop_table("domain_event_outbox")
    op.drop_table("file_object")
