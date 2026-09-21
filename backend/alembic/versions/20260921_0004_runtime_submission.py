"""add runtime submission projection

Revision ID: 20260921_0004
Revises: 20260921_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0004"
down_revision = "20260921_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("runtime_release_read_model",
        sa.Column("lab_release_id", sa.String(36), primary_key=True), sa.Column("lab_version_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False), sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("spec_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_runtime_release_class_status", "runtime_release_read_model", ["class_id", "status"])
    op.add_column("runtime_request", sa.Column("submission_status", sa.String(24), nullable=False, server_default="DRAFT"))
    op.add_column("runtime_request", sa.Column("submitted_at", sa.DateTime(), nullable=True))
    op.add_column("runtime_request", sa.Column("last_activity_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("runtime_request", "last_activity_at")
    op.drop_column("runtime_request", "submitted_at")
    op.drop_column("runtime_request", "submission_status")
    op.drop_index("ix_runtime_release_class_status", table_name="runtime_release_read_model")
    op.drop_table("runtime_release_read_model")
