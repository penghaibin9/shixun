from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class Resource(Base):
    __tablename__ = "resource"
    __table_args__ = (Index("ix_resource_filter", "course_id", "status", "resource_type", "name"),)
    resource_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    lesson_id: Mapped[str | None] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    resource_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ResourceVersion(Base):
    __tablename__ = "resource_version"
    __table_args__ = (UniqueConstraint("resource_id", "version_no", name="uq_resource_version_no"),)
    resource_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resource.resource_id", ondelete="RESTRICT"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[str] = mapped_column(ForeignKey("file_object.file_id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class LessonResource(Base):
    __tablename__ = "lesson_resource"
    __table_args__ = (UniqueConstraint("course_id", "lesson_id", name="uq_lesson_resource_contract"), Index("ix_lesson_resource_kind", "course_id", "lesson_kind", "lesson_code"))
    lesson_resource_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36))
    lesson_id: Mapped[str] = mapped_column(String(36))
    lesson_kind: Mapped[str] = mapped_column(String(16))
    chapter_no: Mapped[int | None] = mapped_column(Integer)
    lesson_code: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(Text)
    principle: Mapped[str | None] = mapped_column(Text)
    steps_summary: Mapped[str | None] = mapped_column(Text)
    core_experiment: Mapped[str | None] = mapped_column(String(64))
    linked_file_pack_id: Mapped[str | None] = mapped_column(String(36))
    linked_video_resource_id: Mapped[str | None] = mapped_column(String(36))
    linked_lab_definition_id: Mapped[str | None] = mapped_column(String(36))


class ResourceReview(Base):
    __tablename__ = "resource_review"
    resource_review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(String(36))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)


class ResourceQualityCheck(Base):
    __tablename__ = "resource_quality_check"
    resource_quality_check_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    resource_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    check_type: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(16))
    details_json: Mapped[dict] = mapped_column(JSON)
    checked_by: Mapped[str] = mapped_column(String(36))
    checked_at: Mapped[datetime] = mapped_column(DateTime)


class ResourceDeliveryManifest(Base):
    __tablename__ = "resource_delivery_manifest"
    __table_args__ = (UniqueConstraint("course_id", "version_no", name="uq_delivery_manifest_version"),)
    resource_delivery_manifest_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    manifest_json: Mapped[dict] = mapped_column(JSON)
    frozen_by: Mapped[str] = mapped_column(String(36))
    frozen_at: Mapped[datetime] = mapped_column(DateTime)


class PptAsset(Base):
    __tablename__ = "ppt_asset"
    ppt_asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), unique=True)
    knowledge_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    layout_overflow_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    animation_occlusion_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    copyright_noted: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_by: Mapped[str | None] = mapped_column(String(36))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class VideoAsset(Base):
    __tablename__ = "video_asset"
    video_asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), unique=True)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    probed_at: Mapped[datetime] = mapped_column(DateTime)


class LabFilePack(Base):
    __tablename__ = "lab_file_pack"
    lab_file_pack_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_version.resource_version_id", ondelete="RESTRICT"), unique=True)
    file_count: Mapped[int] = mapped_column(Integer)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger)


class QuestionBank(Base):
    __tablename__ = "question_bank"
    question_bank_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Question(Base):
    __tablename__ = "question"
    question_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_bank_id: Mapped[str] = mapped_column(ForeignKey("question_bank.question_bank_id", ondelete="RESTRICT"), index=True)
    question_type: Mapped[str] = mapped_column(String(16))
    stem: Mapped[str] = mapped_column(Text)
    answer_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)


class QuestionOption(Base):
    __tablename__ = "question_option"
    question_option_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("question.question_id", ondelete="CASCADE"), index=True)
    option_key: Mapped[str] = mapped_column(String(8))
    option_text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)


class QuestionExplanation(Base):
    __tablename__ = "question_explanation"
    question_id: Mapped[str] = mapped_column(ForeignKey("question.question_id", ondelete="CASCADE"), primary_key=True)
    explanation: Mapped[str] = mapped_column(Text)


class QuestionLessonMap(Base):
    __tablename__ = "question_lesson_map"
    __table_args__ = (UniqueConstraint("question_id", "lesson_id", name="uq_question_lesson"),)
    question_lesson_map_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("question.question_id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(36), index=True)
