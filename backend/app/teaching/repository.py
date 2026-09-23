from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.resources.models import Question, QuestionBank, QuestionLessonMap, QuestionOption

from . import models as m


class TeachingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, model, object_id: str):
        return self.session.get(model, object_id)

    def add(self, entity):
        self.session.add(entity)
        self.session.flush()
        return entity

    def list_courses(self, course_ids: frozenset[str]):
        stmt = select(m.Course).where(m.Course.course_id.in_(course_ids)).order_by(m.Course.created_at.desc())
        return list(self.session.scalars(stmt))

    def course_lessons(self, course_id: str):
        stmt = (
            select(m.CourseLesson, m.CourseChapter)
            .join(m.CourseChapter, m.CourseChapter.chapter_id == m.CourseLesson.chapter_id)
            .where(m.CourseLesson.course_id == course_id)
            .order_by(m.CourseChapter.sequence, m.CourseLesson.sequence, m.CourseLesson.lesson_id)
        )
        return self.session.execute(stmt).all()

    def course_lesson(self, course_id: str, lesson_id: str):
        return self.session.scalar(
            select(m.CourseLesson).where(
                m.CourseLesson.course_id == course_id,
                m.CourseLesson.lesson_id == lesson_id,
            )
        )

    def list_classes(self, class_ids: frozenset[str]):
        stmt = select(m.TeachingClass).where(m.TeachingClass.class_id.in_(class_ids)).order_by(m.TeachingClass.created_at.desc())
        return list(self.session.scalars(stmt))

    def class_course(self, class_id: str):
        return self.session.scalar(select(m.ClassCourse).where(m.ClassCourse.class_id == class_id))

    def members(self, class_id: str, *, search: str = "", status: str = "ACTIVE", sort: str = "student_number", direction: str = "asc", offset: int = 0, limit: int = 100):
        stmt = select(m.ClassMembership).where(m.ClassMembership.class_id == class_id)
        if status: stmt = stmt.where(m.ClassMembership.status == status)
        if search:
            term = f"%{search}%"
            stmt = stmt.where(m.ClassMembership.student_number.like(term) | m.ClassMembership.student_name.like(term))
        column = m.ClassMembership.student_name if sort == "student_name" else m.ClassMembership.student_number
        stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc())
        total = self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        return list(self.session.scalars(stmt.offset(offset).limit(limit))), total

    def membership(self, class_id: str, student_id: str):
        return self.session.scalar(select(m.ClassMembership).where(m.ClassMembership.class_id == class_id, m.ClassMembership.student_id == student_id))

    def membership_by_number(self, class_id: str, student_number: str):
        return self.session.scalar(select(m.ClassMembership).where(m.ClassMembership.class_id == class_id, m.ClassMembership.student_number == student_number))

    def membership_by_id(self, class_id: str, membership_id: str):
        return self.session.scalar(select(m.ClassMembership).where(m.ClassMembership.class_id == class_id, m.ClassMembership.class_membership_id == membership_id))

    def import_job(self, class_id: str, key: str):
        return self.session.scalar(select(m.ImportJob).where(m.ImportJob.class_id == class_id, m.ImportJob.idempotency_key == key))

    def class_for_update(self, class_id: str):
        return self.session.scalar(select(m.TeachingClass).where(m.TeachingClass.class_id == class_id).with_for_update())

    def attendance_tasks(self, class_ids: frozenset[str]):
        stmt = select(m.AttendanceTask).where(m.AttendanceTask.class_id.in_(class_ids)).order_by(m.AttendanceTask.starts_at.desc())
        return list(self.session.scalars(stmt))

    def attendance_record(self, task_id: str, student_id: str):
        return self.session.scalar(select(m.AttendanceRecord).where(m.AttendanceRecord.task_id == task_id, m.AttendanceRecord.student_id == student_id))

    def attendance_task_by_token_hash(self, token_hash: str, *, lock: bool = False):
        query = select(m.AttendanceTask).where(m.AttendanceTask.sign_token_hash == token_hash)
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)

    def attendance_records(self, task_id: str):
        return list(self.session.scalars(select(m.AttendanceRecord).where(m.AttendanceRecord.task_id == task_id).order_by(m.AttendanceRecord.signed_at)))

    def poll_answer(self, poll_id: str, student_id: str):
        return self.session.scalar(select(m.PollAnswer).where(m.PollAnswer.poll_id == poll_id, m.PollAnswer.student_id == student_id))

    def poll_results(self, poll_id: str):
        stmt = select(m.PollOption.option_id, m.PollOption.label, func.count(m.PollAnswer.answer_id)).outerjoin(m.PollAnswer).where(m.PollOption.poll_id == poll_id).group_by(m.PollOption.option_id, m.PollOption.label).order_by(m.PollOption.sequence)
        return [{"option_id": oid, "label": label, "count": count} for oid, label, count in self.session.execute(stmt)]

    def submission(self, assignment_id: str, student_id: str):
        return self.session.scalar(select(m.AssignmentSubmission).where(m.AssignmentSubmission.assignment_id == assignment_id, m.AssignmentSubmission.student_id == student_id))

    def attempt(self, quiz_id: str, student_id: str):
        return self.session.scalar(select(m.QuizAttempt).where(m.QuizAttempt.quiz_id == quiz_id, m.QuizAttempt.student_id == student_id))

    def published_assignments(self, class_ids: frozenset[str]):
        stmt = (
            select(m.Assignment)
            .where(m.Assignment.class_id.in_(class_ids), m.Assignment.status == "PUBLISHED")
            .order_by(m.Assignment.due_at, m.Assignment.assignment_id)
        )
        return list(self.session.scalars(stmt))

    def published_quizzes(self, class_ids: frozenset[str]):
        stmt = (
            select(m.Quiz)
            .where(m.Quiz.class_id.in_(class_ids), m.Quiz.status == "PUBLISHED")
            .order_by(m.Quiz.quiz_id)
        )
        return list(self.session.scalars(stmt))

    def published_questions_for_freeze(self, course_id: str, question_ids: list[str]):
        """Read and lock the B-owned question facts A is allowed to freeze.

        No client snapshot, version or score travels through this boundary.
        PUBLISHED questions are immutable in B's application state machine; the
        lock additionally prevents a concurrent legacy write from racing the
        snapshot transaction.
        """

        stmt = (
            select(Question, QuestionLessonMap.lesson_id)
            .join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id)
            .join(QuestionLessonMap, QuestionLessonMap.question_id == Question.question_id)
            .where(
                Question.question_id.in_(question_ids),
                Question.status == "PUBLISHED",
                QuestionBank.course_id == course_id,
            )
            .with_for_update()
        )
        return list(self.session.execute(stmt))

    def question_options_for_freeze(self, question_id: str):
        return list(
            self.session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == question_id)
                .order_by(QuestionOption.option_key, QuestionOption.question_option_id)
            )
        )
