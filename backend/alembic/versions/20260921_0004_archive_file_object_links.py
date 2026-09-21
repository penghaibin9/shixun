"""link archives to gradebooks and shared file objects

Revision ID: 20260921_0004
Revises: 20260921_0003
"""
from alembic import op

revision = "20260921_0004"
down_revision = "20260921_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key("fk_course_archive_gradebook", "course_archive", "gradebook", ["gradebook_id"], ["gradebook_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_course_archive_artifact_file", "course_archive_artifact", "file_object", ["file_id"], ["file_id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_course_archive_artifact_file", "course_archive_artifact", type_="foreignkey")
    op.drop_constraint("fk_course_archive_gradebook", "course_archive", type_="foreignkey")
