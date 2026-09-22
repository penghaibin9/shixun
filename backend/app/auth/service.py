from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.outbox import enqueue_event

from . import models as m
from .repository import AuthRepository
from .schemas import AccountCreate


def now() -> datetime:
    return datetime.utcnow()


class AuthService:
    def __init__(self, session: Session, user: UserContext):
        self.session = session
        self.user = user
        self.repo = AuthRepository(session)

    def require_admin(self, permission: str) -> None:
        if self.user.role != "admin" or permission not in self.user.permissions:
            raise ApiError("AUTH.FORBIDDEN", "当前账号没有账号档案管理权限", 403)

    @staticmethod
    def _view(user: m.AuthUser, repo: AuthRepository) -> dict:
        teacher = repo.session.scalar(select(m.TeacherProfile).where(m.TeacherProfile.user_id == user.user_id))
        student = repo.session.scalar(select(m.StudentProfile).where(m.StudentProfile.user_id == user.user_id))
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "role": user.primary_role_code,
            "status": user.status,
            "external_subject": user.external_subject,
            "login_name": user.login_name,
            "teacher_id": teacher.teacher_id if teacher else None,
            "staff_number": teacher.staff_number if teacher else None,
            "student_id": student.student_id if student else None,
            "student_number": student.student_number if student else None,
            "phone": student.phone if student else None,
            "email": student.email if student else None,
        }

    def create_account(self, body: AccountCreate) -> dict:
        self.require_admin("auth.accounts.write")
        role = self.repo.role_by_code(body.role)
        if not role:
            raise ApiError("AUTH.ROLE_NOT_CONFIGURED", "账号角色尚未初始化", 409)
        stamp = now()
        user = m.AuthUser(
            user_id=str(uuid4()),
            external_subject=body.external_subject,
            login_name=body.login_name,
            display_name=body.display_name,
            status=body.status,
            primary_role_code=body.role,
            created_at=stamp,
            updated_at=stamp,
        )
        try:
            self.repo.add(user)
            self.repo.add(m.AuthUserRole(auth_user_role_id=str(uuid4()), user_id=user.user_id, role_id=role.role_id, assigned_at=stamp))
            if body.role == "teacher":
                self.repo.add(
                    m.TeacherProfile(
                        teacher_id=body.teacher_id or str(uuid4()),
                        user_id=user.user_id,
                        staff_number=body.staff_number,
                        display_name=body.display_name,
                        status=body.status,
                        created_at=stamp,
                        updated_at=stamp,
                    )
                )
            elif body.role == "student":
                self.repo.add(
                    m.StudentProfile(
                        student_id=body.student_id or str(uuid4()),
                        user_id=user.user_id,
                        student_number=body.student_number or "",
                        full_name=body.display_name,
                        phone=body.phone,
                        email=body.email,
                        status=body.status,
                        created_at=stamp,
                        updated_at=stamp,
                    )
                )
            enqueue_event(
                self.session,
                event_type="auth.account.created",
                aggregate_type="auth_user",
                aggregate_id=user.user_id,
                actor_user_id=self.user.user_id,
                idempotency_key=f"auth.account.created:{user.user_id}",
                payload={"user_id": user.user_id, "role": body.role, "status": body.status},
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiError("AUTH.ACCOUNT_CONFLICT", "登录名、外部身份、工号或学号已存在", 409) from exc
        return self._view(user, self.repo)

    def get_account(self, user_id: str) -> dict:
        self.require_admin("auth.accounts.read")
        user = self.repo.user(user_id)
        if not user:
            raise ApiError("AUTH.ACCOUNT_NOT_FOUND", "账号不存在", 404)
        return self._view(user, self.repo)

    def list_accounts(self, *, search: str = "", role: str | None = None, status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
        self.require_admin("auth.accounts.read")
        rows, total = self.repo.accounts(search=search, role=role, status=status, offset=(page - 1) * page_size, limit=page_size)
        return {"items": [self._view(row, self.repo) for row in rows], "page": page, "page_size": page_size, "total": total}

    def scan_identity_reconciliation(self) -> dict:
        """记录旧名单与权威学生档案的差异，不修改任何历史 membership。"""

        self.require_admin("auth.reconciliation.scan")
        # A 域仍拥有 class_membership。本查询只生成可审计的待核对事项，
        # 以避免在没有人工确认时替换旧 student_id。
        from app.teaching import models as teaching_models

        examined_count = valid_count = created_case_count = existing_case_count = 0
        memberships = self.session.scalars(
            select(teaching_models.ClassMembership).order_by(
                teaching_models.ClassMembership.class_id,
                teaching_models.ClassMembership.class_membership_id,
            )
        )
        for membership in memberships:
            examined_count += 1
            profile = self.repo.student_profile_by_number(membership.student_number)
            account = self.repo.user(profile.user_id) if profile else None
            reason_code: str | None = None
            canonical_student_id: str | None = None
            details: dict[str, object] = {}
            if not profile:
                reason_code = "STUDENT_PROFILE_NOT_FOUND"
                details = {"message": "历史班级成员的学号没有学生档案"}
            elif profile.status != "ACTIVE" or not account or account.status != "ACTIVE":
                reason_code = "STUDENT_PROFILE_DISABLED"
                canonical_student_id = profile.student_id
                details = {"message": "学生档案或账号已停用", "student_id": profile.student_id}
            elif profile.full_name.strip() != membership.student_name.strip():
                reason_code = "STUDENT_NAME_CONFLICT"
                canonical_student_id = profile.student_id
                details = {"message": "历史名单姓名与学生档案不一致", "profile_name": profile.full_name, "student_id": profile.student_id}
            elif profile.student_id != membership.student_id:
                reason_code = "MEMBERSHIP_IDENTITY_CONFLICT"
                canonical_student_id = profile.student_id
                details = {
                    "message": "历史班级成员 student_id 与权威学生档案不一致",
                    "membership_student_id": membership.student_id,
                    "profile_student_id": profile.student_id,
                }
            else:
                valid_count += 1
                continue

            existing = self.repo.reconciliation_case(membership.student_id, membership.class_id)
            if existing:
                existing_case_count += 1
                continue
            self.repo.add(
                m.IdentityReconciliationCase(
                    reconciliation_case_id=str(uuid4()),
                    legacy_student_id=membership.student_id,
                    canonical_student_id=canonical_student_id,
                    class_id=membership.class_id,
                    student_number=membership.student_number,
                    observed_name=membership.student_name,
                    observed_phone=membership.phone,
                    observed_email=membership.email,
                    reason_code=reason_code,
                    status="PENDING",
                    details_json=details,
                    created_by=self.user.user_id,
                    created_at=now(),
                    resolved_by=None,
                    resolved_at=None,
                )
            )
            created_case_count += 1
        enqueue_event(
            self.session,
            event_type="auth.identity.reconciliation.scanned",
            aggregate_type="identity_reconciliation",
            aggregate_id="all_class_memberships",
            actor_user_id=self.user.user_id,
            idempotency_key=f"auth.identity.reconciliation.scanned:{uuid4()}",
            payload={
                "examined_count": examined_count,
                "valid_count": valid_count,
                "created_case_count": created_case_count,
                "existing_case_count": existing_case_count,
            },
        )
        self.session.commit()
        return {
            "examined_count": examined_count,
            "valid_count": valid_count,
            "created_case_count": created_case_count,
            "existing_case_count": existing_case_count,
        }
