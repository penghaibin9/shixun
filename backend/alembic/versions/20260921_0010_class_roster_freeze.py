"""add durable class roster freeze

Revision ID: 20260921_0010
Revises: 20260921_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0010"
down_revision = "20260921_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("class", sa.Column("roster_frozen_at", sa.DateTime(), nullable=True))
    op.add_column("class", sa.Column("roster_frozen_by", sa.String(36), nullable=True))
    op.add_column("class", sa.Column("roster_snapshot_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("class", "roster_snapshot_hash")
    op.drop_column("class", "roster_frozen_by")
    op.drop_column("class", "roster_frozen_at")
