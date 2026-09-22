from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m


class AuthRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, entity):
        self.session.add(entity)
        self.session.flush()
        return entity

    def role_by_code(self, code: str):
        return self.session.scalar(select(m.AuthRole).where(m.AuthRole.code == code))

    def user(self, user_id: str):
        return self.session.get(m.AuthUser, user_id)

    def student_profile_by_number(self, student_number: str):
        return self.session.scalar(select(m.StudentProfile).where(m.StudentProfile.student_number == student_number))

    def student_profile(self, student_id: str):
        return self.session.get(m.StudentProfile, student_id)

    def teacher_profile(self, teacher_id: str):
        return self.session.get(m.TeacherProfile, teacher_id)

    def reconciliation_case(self, legacy_student_id: str | None, class_id: str | None):
        if legacy_student_id is None:
            return None
        return self.session.scalar(
            select(m.IdentityReconciliationCase).where(
                m.IdentityReconciliationCase.legacy_student_id == legacy_student_id,
                m.IdentityReconciliationCase.class_id == class_id,
            )
        )

    def accounts(self, *, search: str = "", role: str | None = None, status: str | None = None, offset: int = 0, limit: int = 20):
        stmt = select(m.AuthUser).order_by(m.AuthUser.created_at.desc(), m.AuthUser.user_id)
        if search:
            term = f"%{search}%"
            stmt = stmt.where(m.AuthUser.display_name.like(term) | m.AuthUser.login_name.like(term))
        if role:
            stmt = stmt.where(m.AuthUser.primary_role_code == role)
        if status:
            stmt = stmt.where(m.AuthUser.status == status)
        total = self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        return list(self.session.scalars(stmt.offset(offset).limit(limit))), total
