from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class RuntimeProjection(Base):
    __tablename__ = "classroom_runtime_projection"
    __table_args__ = (
        UniqueConstraint("lab_release_id", "student_id", name="uq_classroom_release_student"),
        Index("ix_classroom_scope_status", "class_id", "lab_release_id", "status"),
    )
    projection_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_release_id: Mapped[str] = mapped_column(String(36), index=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    runtime_instance_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(32))
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    raw_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    max_score: Mapped[float] = mapped_column(Numeric(8, 2), default=100)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ConsumedRuntimeEvent(Base):
    __tablename__ = "classroom_consumed_event"
    __table_args__ = (UniqueConstraint("event_type", "idempotency_key", name="uq_classroom_event_idempotency"),)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime] = mapped_column(DateTime)


class ClassroomRuntimeEvent(Base):
    __tablename__ = "classroom_runtime_event"
    event_sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    lab_release_id: Mapped[str] = mapped_column(String(36), index=True)
    student_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)


class TeachingLogDistributionTask(Base):
    __tablename__ = "teaching_log_distribution_task"
    __table_args__ = (UniqueConstraint("class_id", "idempotency_key", name="uq_log_distribution_idempotency"),)
    distribution_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    lab_release_id: Mapped[str] = mapped_column(String(36), index=True)
    distribution_type: Mapped[str] = mapped_column(String(24))
    source_filter_json: Mapped[dict] = mapped_column(JSON)
    requested_count: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    instruction: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class TeachingLogDistributionItem(Base):
    __tablename__ = "teaching_log_distribution_item"
    __table_args__ = (UniqueConstraint("distribution_id", "artifact_id", name="uq_distribution_artifact"),)
    item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    distribution_id: Mapped[str] = mapped_column(ForeignKey("teaching_log_distribution_task.distribution_id", ondelete="CASCADE"), index=True)
    artifact_id: Mapped[str] = mapped_column(String(36), index=True)
    source_system: Mapped[str] = mapped_column(String(16))
    source_student_id: Mapped[str | None] = mapped_column(String(36))
    artifact_type: Mapped[str] = mapped_column(String(24))
    artifact_meta_json: Mapped[dict] = mapped_column(JSON)


class StudentLogAssignment(Base):
    __tablename__ = "student_log_assignment"
    __table_args__ = (UniqueConstraint("distribution_id", "student_id", name="uq_distribution_student"),)
    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    distribution_id: Mapped[str] = mapped_column(ForeignKey("teaching_log_distribution_task.distribution_id", ondelete="CASCADE"), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24))
    assigned_at: Mapped[datetime] = mapped_column(DateTime)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
