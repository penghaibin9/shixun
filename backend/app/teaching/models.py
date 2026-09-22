from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class Course(Base):
    __tablename__ = "course"
    course_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    term: Mapped[str] = mapped_column(String(64))
    owner_teacher_id: Mapped[str] = mapped_column(String(36), index=True)
    major: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CourseChapter(Base):
    __tablename__ = "course_chapter"
    __table_args__ = (
        UniqueConstraint("course_id", "sequence", name="uq_chapter_course_sequence"),
        UniqueConstraint("course_id", "chapter_id", name="uq_course_chapter_scope"),
    )
    chapter_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    sequence: Mapped[int] = mapped_column(Integer)


class CourseLesson(Base):
    __tablename__ = "course_lesson"
    __table_args__ = (
        UniqueConstraint("chapter_id", "sequence", name="uq_lesson_chapter_sequence"),
        UniqueConstraint("course_id", "lesson_id", name="uq_course_lesson_scope"),
        UniqueConstraint("course_id", "lesson_code", name="uq_course_lesson_code"),
        ForeignKeyConstraint(
            ["course_id", "chapter_id"],
            ["course_chapter.course_id", "course_chapter.chapter_id"],
            name="fk_course_lesson_chapter_scope",
            ondelete="CASCADE",
        ),
    )
    lesson_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[str] = mapped_column(String(36), index=True)
    lesson_code: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column(Integer)
    lesson_type: Mapped[str] = mapped_column(String(24), default="THEORY")


class TeachingClass(Base):
    __tablename__ = "class"
    class_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    term: Mapped[str] = mapped_column(String(64))
    owner_teacher_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    roster_frozen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    roster_frozen_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    roster_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ClassCourse(Base):
    __tablename__ = "class_course"
    __table_args__ = (UniqueConstraint("class_id", "course_id", name="uq_class_course"),)
    class_course_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id", ondelete="CASCADE"), index=True)


class ClassMembership(Base):
    __tablename__ = "class_membership"
    __table_args__ = (
        UniqueConstraint("class_id", "student_id", name="uq_membership_class_student"),
        UniqueConstraint("class_id", "student_number", name="uq_membership_class_number"),
    )
    class_membership_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    student_number: Mapped[str] = mapped_column(String(64))
    student_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(DateTime)


class TeachingTeacherAssignment(Base):
    __tablename__ = "teaching_teacher_assignment"
    __table_args__ = (UniqueConstraint("teacher_id", "class_id", "course_id", name="uq_teacher_class_course"),)
    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id", ondelete="CASCADE"), index=True)


class ImportJob(Base):
    __tablename__ = "teaching_import_job"
    __table_args__ = (UniqueConstraint("class_id", "idempotency_key", name="uq_import_class_idempotency"),)
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_rows_json: Mapped[list] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AttendanceTask(Base):
    __tablename__ = "attendance_task"
    __table_args__ = (Index("ix_attendance_scope_status", "course_id", "class_id", "status"),)
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id"), index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("course_lesson.lesson_id"), index=True)
    task_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(160))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    sign_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))


class AttendanceRecord(Base):
    __tablename__ = "attendance_record"
    __table_args__ = (UniqueConstraint("task_id", "student_id", name="uq_attendance_task_student"),)
    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("attendance_task.task_id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime)
    result: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(24))


class Poll(Base):
    __tablename__ = "poll"
    poll_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id"), index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("course_lesson.lesson_id"))
    poll_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))


class PollOption(Base):
    __tablename__ = "poll_option"
    option_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    poll_id: Mapped[str] = mapped_column(ForeignKey("poll.poll_id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    sequence: Mapped[int] = mapped_column(Integer)


class PollAnswer(Base):
    __tablename__ = "poll_answer"
    __table_args__ = (UniqueConstraint("poll_id", "student_id", name="uq_poll_student"),)
    answer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    poll_id: Mapped[str] = mapped_column(ForeignKey("poll.poll_id", ondelete="CASCADE"), index=True)
    option_id: Mapped[str] = mapped_column(ForeignKey("poll_option.option_id"))
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime)


class Assignment(Base):
    __tablename__ = "assignment"
    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id"), index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("course_lesson.lesson_id"))
    title: Mapped[str] = mapped_column(String(160))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    random_order: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))


class AssignmentQuestionRef(Base):
    __tablename__ = "assignment_question_ref"
    ref_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignment.assignment_id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(String(36))
    # This is a server-derived SHA256 of the frozen B question content, not a
    # version supplied by the browser when the assignment is created.
    question_version: Mapped[str] = mapped_column(String(64))
    question_snapshot: Mapped[dict] = mapped_column(JSON)
    max_score: Mapped[int] = mapped_column(Integer)


class AssignmentSubmission(Base):
    __tablename__ = "assignment_submission"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_assignment_student"),)
    submission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignment.assignment_id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    answers_json: Mapped[dict] = mapped_column(JSON)
    raw_score: Mapped[float] = mapped_column(Numeric(8, 2))
    max_score: Mapped[float] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(24), default="SUBMITTED")
    submitted_at: Mapped[datetime] = mapped_column(DateTime)


class Quiz(Base):
    __tablename__ = "quiz"
    quiz_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("course.course_id"), index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class.class_id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("course_lesson.lesson_id"))
    title: Mapped[str] = mapped_column(String(160))
    time_limit_minutes: Mapped[int] = mapped_column(Integer)
    random_order: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36))


class QuizQuestionRef(Base):
    __tablename__ = "quiz_question_ref"
    ref_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quiz.quiz_id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(String(36))
    # This is a server-derived SHA256 of the frozen B question content, not a
    # version supplied by the browser when the quiz is created.
    question_version: Mapped[str] = mapped_column(String(64))
    question_snapshot: Mapped[dict] = mapped_column(JSON)
    max_score: Mapped[int] = mapped_column(Integer)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempt"
    __table_args__ = (UniqueConstraint("quiz_id", "student_id", name="uq_quiz_student"),)
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quiz.quiz_id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    started_at: Mapped[datetime] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_score: Mapped[float | None] = mapped_column(Numeric(8, 2))
    max_score: Mapped[float | None] = mapped_column(Numeric(8, 2))


class QuizAnswer(Base):
    __tablename__ = "quiz_answer"
    __table_args__ = (UniqueConstraint("attempt_id", "question_ref_id", name="uq_quiz_answer_question"),)
    answer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("quiz_attempt.attempt_id", ondelete="CASCADE"), index=True)
    question_ref_id: Mapped[str] = mapped_column(ForeignKey("quiz_question_ref.ref_id"))
    answer_json: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Numeric(8, 2), default=0)


class TeachingScoreProof(Base):
    """A-owned, immutable evidence for a server-calculated assignment/quiz score.

    The record is deliberately separate from F's gradebook proof projection.  A
    writes it in the same transaction as the submission/attempt and its two
    outbox events; F consumes the proof event independently before accepting the
    score event.
    """

    __tablename__ = "teaching_score_proof"
    __table_args__ = (
        UniqueConstraint("source_fact_id", name="uq_teaching_score_proof_source_fact"),
        UniqueConstraint("score_event_id", name="uq_teaching_score_proof_score_event"),
        UniqueConstraint("score_proof_event_id", name="uq_teaching_score_proof_event"),
        Index("ix_teaching_score_proof_scope", "course_id", "class_id", "student_id"),
    )

    proof_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_fact_id: Mapped[str] = mapped_column(String(36))
    score_event_id: Mapped[str] = mapped_column(String(36))
    score_proof_event_id: Mapped[str] = mapped_column(String(36))
    score_aggregate_id: Mapped[str] = mapped_column(String(36))
    course_id: Mapped[str] = mapped_column(String(36), index=True)
    class_id: Mapped[str] = mapped_column(String(36), index=True)
    lesson_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    raw_score: Mapped[float] = mapped_column(Numeric(8, 2))
    max_score: Mapped[float] = mapped_column(Numeric(8, 2))
    contract: Mapped[str] = mapped_column(String(64))
    issuer: Mapped[str] = mapped_column(String(48))
    origin: Mapped[str] = mapped_column(String(32))
    evidence_type: Mapped[str] = mapped_column(String(64))
    frozen_question_count: Mapped[int] = mapped_column(Integer)
    frozen_question_sha256: Mapped[str] = mapped_column(String(64))
    answer_evidence_sha256: Mapped[str] = mapped_column(String(64))
    scoring_evidence_sha256: Mapped[str] = mapped_column(String(64))
    score_payload_sha256: Mapped[str] = mapped_column(String(64))
    frozen_question_evidence_json: Mapped[list] = mapped_column(JSON)
    answer_evidence_json: Mapped[list] = mapped_column(JSON)
    scoring_evidence_json: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
