"""create course resource domain tables and 37/12 requirement catalog

Revision ID: 20260921_0002
Revises: f4e75e84c503
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

from app.resources.catalog import lesson_rows

revision = "20260921_0002"
down_revision = "f4e75e84c503"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("resource",
        sa.Column("resource_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("lesson_id", sa.String(36)), sa.Column("name", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_resource_course_id", "resource", ["course_id"])
    op.create_index("ix_resource_lesson_id", "resource", ["lesson_id"])
    op.create_index("ix_resource_filter", "resource", ["course_id", "status", "resource_type", "name"])
    op.create_table("lesson_resource",
        sa.Column("lesson_resource_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("lesson_id", sa.String(36), nullable=False), sa.Column("lesson_kind", sa.String(16), nullable=False),
        sa.Column("chapter_no", sa.Integer()), sa.Column("lesson_code", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("purpose", sa.Text()), sa.Column("environment", sa.Text()),
        sa.Column("principle", sa.Text()), sa.Column("steps_summary", sa.Text()), sa.Column("core_experiment", sa.String(64)),
        sa.Column("linked_file_pack_id", sa.String(36)), sa.Column("linked_video_resource_id", sa.String(36)),
        sa.Column("linked_lab_definition_id", sa.String(36)),
        sa.UniqueConstraint("course_id", "lesson_id", name="uq_lesson_resource_contract"))
    op.create_index("ix_lesson_resource_kind", "lesson_resource", ["course_id", "lesson_kind", "lesson_code"])
    lesson_table = sa.table("lesson_resource", *[sa.column(name) for name in lesson_rows()[0]])
    op.bulk_insert(lesson_table, lesson_rows())
    op.create_table("resource_version",
        sa.Column("resource_version_id", sa.String(36), primary_key=True),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("resource.resource_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("file_object.file_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.String(36)), sa.Column("reviewed_at", sa.DateTime()), sa.Column("published_at", sa.DateTime()),
        sa.UniqueConstraint("resource_id", "version_no", name="uq_resource_version_no"))
    op.create_index("ix_resource_version_resource_id", "resource_version", ["resource_id"])
    op.create_table("resource_review",
        sa.Column("resource_review_id", sa.String(36), primary_key=True),
        sa.Column("resource_version_id", sa.String(36), sa.ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False), sa.Column("comment", sa.Text()),
        sa.Column("reviewer_id", sa.String(36), nullable=False), sa.Column("reviewed_at", sa.DateTime(), nullable=False))
    op.create_index("ix_resource_review_resource_version_id", "resource_review", ["resource_version_id"])
    op.create_table("resource_quality_check",
        sa.Column("resource_quality_check_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("resource_version_id", sa.String(36)), sa.Column("check_type", sa.String(32), nullable=False),
        sa.Column("result", sa.String(16), nullable=False), sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("checked_by", sa.String(36), nullable=False), sa.Column("checked_at", sa.DateTime(), nullable=False))
    op.create_index("ix_resource_quality_check_course_id", "resource_quality_check", ["course_id"])
    op.create_index("ix_resource_quality_check_resource_version_id", "resource_quality_check", ["resource_version_id"])
    op.create_table("resource_delivery_manifest",
        sa.Column("resource_delivery_manifest_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False), sa.Column("frozen_by", sa.String(36), nullable=False),
        sa.Column("frozen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "version_no", name="uq_delivery_manifest_version"))
    op.create_index("ix_resource_delivery_manifest_course_id", "resource_delivery_manifest", ["course_id"])
    op.create_table("ppt_asset",
        sa.Column("ppt_asset_id", sa.String(36), primary_key=True),
        sa.Column("resource_version_id", sa.String(36), sa.ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("knowledge_complete", sa.Boolean(), nullable=False), sa.Column("layout_overflow_passed", sa.Boolean(), nullable=False),
        sa.Column("animation_occlusion_passed", sa.Boolean(), nullable=False), sa.Column("copyright_noted", sa.Boolean(), nullable=False),
        sa.Column("checked_by", sa.String(36)), sa.Column("checked_at", sa.DateTime()))
    op.create_table("video_asset",
        sa.Column("video_asset_id", sa.String(36), primary_key=True),
        sa.Column("resource_version_id", sa.String(36), sa.ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False), sa.Column("width", sa.Integer()), sa.Column("height", sa.Integer()),
        sa.Column("probed_at", sa.DateTime(), nullable=False))
    op.create_table("lab_file_pack",
        sa.Column("lab_file_pack_id", sa.String(36), primary_key=True),
        sa.Column("resource_version_id", sa.String(36), sa.ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("file_count", sa.Integer(), nullable=False), sa.Column("total_size_bytes", sa.BigInteger(), nullable=False))
    op.create_table("question_bank",
        sa.Column("question_bank_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_question_bank_course_id", "question_bank", ["course_id"])
    op.create_table("question",
        sa.Column("question_id", sa.String(36), primary_key=True),
        sa.Column("question_bank_id", sa.String(36), sa.ForeignKey("question_bank.question_bank_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question_type", sa.String(16), nullable=False), sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("answer_json", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.String(36)), sa.Column("reviewed_at", sa.DateTime()))
    op.create_index("ix_question_question_bank_id", "question", ["question_bank_id"])
    op.create_table("question_option",
        sa.Column("question_option_id", sa.String(36), primary_key=True),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("question.question_id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_key", sa.String(8), nullable=False), sa.Column("option_text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False))
    op.create_index("ix_question_option_question_id", "question_option", ["question_id"])
    op.create_table("question_explanation",
        sa.Column("question_id", sa.String(36), sa.ForeignKey("question.question_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("explanation", sa.Text(), nullable=False))
    op.create_table("question_lesson_map",
        sa.Column("question_lesson_map_id", sa.String(36), primary_key=True),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("question.question_id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(36), nullable=False),
        sa.UniqueConstraint("question_id", "lesson_id", name="uq_question_lesson"))
    op.create_index("ix_question_lesson_map_question_id", "question_lesson_map", ["question_id"])
    op.create_index("ix_question_lesson_map_lesson_id", "question_lesson_map", ["lesson_id"])


def downgrade() -> None:
    for table in ["question_lesson_map", "question_explanation", "question_option", "question", "question_bank", "lab_file_pack", "video_asset", "ppt_asset", "resource_delivery_manifest", "resource_quality_check", "resource_review", "resource_version", "lesson_resource", "resource"]:
        op.drop_table(table)
