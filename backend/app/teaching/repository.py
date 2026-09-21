from sqlalchemy import func, select
from sqlalchemy.orm import Session

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

    def list_classes(self, class_ids: frozenset[str]):
        stmt = select(m.TeachingClass).where(m.TeachingClass.class_id.in_(class_ids)).order_by(m.TeachingClass.created_at.desc())
        return list(self.session.scalars(stmt))

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

    def attendance_tasks(self, class_ids: frozenset[str]):
        stmt = select(m.AttendanceTask).where(m.AttendanceTask.class_id.in_(class_ids)).order_by(m.AttendanceTask.starts_at.desc())
        return list(self.session.scalars(stmt))

    def attendance_record(self, task_id: str, student_id: str):
        return self.session.scalar(select(m.AttendanceRecord).where(m.AttendanceRecord.task_id == task_id, m.AttendanceRecord.student_id == student_id))

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
