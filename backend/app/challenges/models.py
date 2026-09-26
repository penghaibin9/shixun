from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class ChallengeDefinition(Base):
    __tablename__ = "challenge_definition"
    __table_args__ = (
        ForeignKeyConstraint(
            ["course_id", "lesson_id"],
            ["course_lesson.course_id", "course_lesson.lesson_id"],
            name="fk_challenge_course_lesson",
            ondelete="RESTRICT",
        ),
        Index("ix_challenge_course_status", "course_id", "status"),
    )
    challenge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lesson_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lab_definition_id: Mapped[str | None] = mapped_column(ForeignKey("lab_definition.lab_definition_id", ondelete="RESTRICT"), nullable=True)
    lab_version_id: Mapped[str | None] = mapped_column(ForeignKey("lab_version.lab_version_id", ondelete="RESTRICT"), nullable=True)
    checkpoint_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prerequisite_challenge_id: Mapped[str | None] = mapped_column(
        ForeignKey("challenge_definition.challenge_id", ondelete="RESTRICT"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(24))
    max_attempts: Mapped[int] = mapped_column(Integer, default=10)
    validation_mode: Mapped[str] = mapped_column(String(32), default="FLAG_AND_CHECKPOINT")
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChallengeHint(Base):
    __tablename__ = "challenge_hint"
    __table_args__ = (UniqueConstraint("challenge_id", "sequence", name="uq_challenge_hint_sequence"),)
    hint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    challenge_id: Mapped[str] = mapped_column(ForeignKey("challenge_definition.challenge_id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    unlock_after_attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ChallengeFlag(Base):
    __tablename__ = "challenge_flag"
    flag_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    challenge_id: Mapped[str] = mapped_column(ForeignKey("challenge_definition.challenge_id", ondelete="CASCADE"), unique=True)
    salt: Mapped[str] = mapped_column(String(64))
    flag_hash: Mapped[str] = mapped_column(String(64))
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=True)
    configured_by: Mapped[str] = mapped_column(String(36))
    configured_at: Mapped[datetime] = mapped_column(DateTime)


class ChallengeAttempt(Base):
    __tablename__ = "challenge_attempt"
    __table_args__ = (
        UniqueConstraint("challenge_id", "student_id", "attempt_no", name="uq_challenge_student_attempt"),
        Index("ix_challenge_attempt_scope", "challenge_id", "student_id", "created_at"),
    )
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    challenge_id: Mapped[str] = mapped_column(ForeignKey("challenge_definition.challenge_id", ondelete="CASCADE"))
    student_id: Mapped[str] = mapped_column(String(36))
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id", ondelete="RESTRICT"))
    lab_release_id: Mapped[str | None] = mapped_column(ForeignKey("lab_release.lab_release_id", ondelete="RESTRICT"), nullable=True)
    runtime_instance_id: Mapped[str | None] = mapped_column(ForeignKey("runtime_instance.runtime_instance_id", ondelete="RESTRICT"), nullable=True)
    checkpoint_result_id: Mapped[str | None] = mapped_column(ForeignKey("checkpoint_result.checkpoint_result_id", ondelete="RESTRICT"), nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime)
