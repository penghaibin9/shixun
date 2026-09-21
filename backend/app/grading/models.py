from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class GradingPolicy(Base):
    __tablename__ = "grading_policy"
    __table_args__ = (UniqueConstraint("course_id", "version_no", name="uq_grading_policy_version"),)
    grading_policy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    effective_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class GradingPolicyItem(Base):
    __tablename__ = "grading_policy_item"
    __table_args__ = (UniqueConstraint("grading_policy_id", "component", name="uq_policy_component"),)
    grading_policy_item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grading_policy_id: Mapped[str] = mapped_column(ForeignKey("grading_policy.grading_policy_id", ondelete="RESTRICT"), index=True)
    component: Mapped[str] = mapped_column(String(24))
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))


class GradeEvent(Base):
    __tablename__ = "grade_event"
    __table_args__ = (UniqueConstraint("event_id", name="uq_grade_event_source_event"), Index("ix_grade_event_scope", "course_id", "class_id", "student_id", "source_type"))
    grade_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36))
    class_id: Mapped[str] = mapped_column(String(36))
    lesson_id: Mapped[str | None] = mapped_column(String(36))
    student_id: Mapped[str] = mapped_column(String(36))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(36))
    raw_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    normalized_score: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    event_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[dict] = mapped_column(JSON)


class Gradebook(Base):
    __tablename__ = "gradebook"
    __table_args__ = (UniqueConstraint("course_id", "class_id", "policy_version", name="uq_gradebook_policy"),)
    gradebook_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    calculated_at: Mapped[datetime] = mapped_column(DateTime)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)


class GradebookItem(Base):
    __tablename__ = "gradebook_item"
    __table_args__ = (UniqueConstraint("gradebook_id", "student_id", "component", name="uq_gradebook_student_component"),)
    gradebook_item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    component: Mapped[str] = mapped_column(String(24))
    component_score: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    weighted_score: Mapped[Decimal] = mapped_column(Numeric(6, 2))


class StudentCourseScore(Base):
    __tablename__ = "student_course_score"
    __table_args__ = (UniqueConstraint("gradebook_id", "student_id", name="uq_student_course_score"),)
    student_course_score_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    completeness: Mapped[str] = mapped_column(String(16))


class AnalyticsCourseSummary(Base):
    __tablename__ = "analytics_course_summary"
    analytics_course_summary_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), unique=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    summary_json: Mapped[dict] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime)


class AnalyticsSectionSummary(Base):
    __tablename__ = "analytics_section_summary"
    __table_args__ = (UniqueConstraint("gradebook_id", "lesson_id", name="uq_analytics_section"),)
    analytics_section_summary_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(36), index=True)
    summary_json: Mapped[dict] = mapped_column(JSON)


class AnalyticsStudentLabSummary(Base):
    __tablename__ = "analytics_student_lab_summary"
    __table_args__ = (UniqueConstraint("gradebook_id", "student_id", name="uq_analytics_student_lab"),)
    analytics_student_lab_summary_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    sum_lab_score: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    submitted_count: Mapped[int] = mapped_column(Integer)
    unsubmitted_count: Mapped[int] = mapped_column(Integer)


class AnalyticsLabSummary(Base):
    __tablename__ = "analytics_lab_summary"
    __table_args__ = (UniqueConstraint("gradebook_id", "lab_release_id", name="uq_analytics_lab"),)
    analytics_lab_summary_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), index=True)
    lab_release_id: Mapped[str] = mapped_column(String(36), index=True)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    submitted_students: Mapped[int] = mapped_column(Integer)
    unsubmitted_students: Mapped[int] = mapped_column(Integer)
    avg_score: Mapped[Decimal] = mapped_column(Numeric(6, 2))


class StudentRiskFlag(Base):
    __tablename__ = "student_risk_flag"
    __table_args__ = (Index("ix_risk_scope", "course_id", "class_id", "student_id", "status"),)
    student_risk_flag_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gradebook_id: Mapped[str] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(String(36))
    class_id: Mapped[str] = mapped_column(String(36))
    student_id: Mapped[str] = mapped_column(String(36))
    risk_type: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CourseArchive(Base):
    __tablename__ = "course_archive"
    __table_args__ = (UniqueConstraint("course_id", "class_id", name="uq_course_archive"),)
    course_archive_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    gradebook_id: Mapped[str | None] = mapped_column(ForeignKey("gradebook.gradebook_id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16))
    precheck_json: Mapped[dict] = mapped_column(JSON)
    manifest_json: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class CourseArchiveArtifact(Base):
    __tablename__ = "course_archive_artifact"
    course_archive_artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_archive_id: Mapped[str] = mapped_column(ForeignKey("course_archive.course_archive_id", ondelete="RESTRICT"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(32))
    file_id: Mapped[str | None] = mapped_column(ForeignKey("file_object.file_id", ondelete="RESTRICT"))
    evidence_ref: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_scope", "course_id", "class_id", "student_id", "occurred_at"), Index("ix_audit_action", "action", "result"))
    audit_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_event_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    actor_user_id: Mapped[str] = mapped_column(String(36))
    actor_role: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(36))
    course_id: Mapped[str | None] = mapped_column(String(36))
    class_id: Mapped[str | None] = mapped_column(String(36))
    student_id: Mapped[str | None] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    details_json: Mapped[dict] = mapped_column(JSON)
