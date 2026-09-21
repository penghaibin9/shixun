"""add teaching member import request digest

Revision ID: 20260921_0012
Revises: 20260921_0011
"""
from alembic import op
import sqlalchemy as sa


revision = "20260921_0012"
down_revision = "20260921_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teaching_import_job", sa.Column("request_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("teaching_import_job", "request_sha256")
