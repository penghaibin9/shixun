"""专属门禁库的最小权威身份档案准备；不包含密码或生产认证凭据。"""

from datetime import datetime

from sqlalchemy import select

from app.auth import models as auth


ROLE_IDS = {"admin": "role_admin", "teacher": "role_teacher", "student": "role_student"}


def _require_role(session, role: str) -> str:
    role_id = ROLE_IDS[role]
    if not session.get(auth.AuthRole, role_id):
        raise RuntimeError("身份权威迁移尚未完成，不能准备门禁学生档案")
    return role_id


def _ensure_role_assignment(session, user_id: str, role: str, stamp: datetime) -> None:
    role_id = _require_role(session, role)
    existing = session.scalar(
        select(auth.AuthUserRole).where(
            auth.AuthUserRole.user_id == user_id,
            auth.AuthUserRole.role_id == role_id,
        )
    )
    if not existing:
        session.add(
            auth.AuthUserRole(
                auth_user_role_id=f"gur-{role}-{user_id}",
                user_id=user_id,
                role_id=role_id,
                assigned_at=stamp,
            )
        )


def ensure_gate_teacher(session, *, teacher_id: str, display_name: str, stamp: datetime) -> None:
    user_id = f"auth-{teacher_id}"
    if not session.get(auth.AuthUser, user_id):
        session.add(
            auth.AuthUser(
                user_id=user_id,
                external_subject=f"gate:{teacher_id}",
                login_name=f"gate-{teacher_id}",
                display_name=display_name,
                status="ACTIVE",
                primary_role_code="teacher",
                created_at=stamp,
                updated_at=stamp,
            )
        )
    _ensure_role_assignment(session, user_id, "teacher", stamp)
    if not session.get(auth.TeacherProfile, teacher_id):
        session.add(
            auth.TeacherProfile(
                teacher_id=teacher_id,
                user_id=user_id,
                staff_number=f"gate-{teacher_id}",
                display_name=display_name,
                status="ACTIVE",
                created_at=stamp,
                updated_at=stamp,
            )
        )


def ensure_gate_student(session, *, student_id: str, student_number: str, full_name: str, stamp: datetime) -> None:
    """在写入班级成员事实前，创建或复用同一全局学生档案。"""

    user_id = f"auth-{student_id}"
    if not session.get(auth.AuthUser, user_id):
        session.add(
            auth.AuthUser(
                user_id=user_id,
                external_subject=f"gate:{student_id}",
                login_name=f"gate-{student_id}",
                display_name=full_name,
                status="ACTIVE",
                primary_role_code="student",
                created_at=stamp,
                updated_at=stamp,
            )
        )
    _ensure_role_assignment(session, user_id, "student", stamp)
    profile = session.get(auth.StudentProfile, student_id)
    if profile:
        if profile.student_number != student_number or profile.full_name != full_name:
            raise RuntimeError("门禁学生档案与既有固定身份不一致")
        return
    duplicate_number = session.scalar(select(auth.StudentProfile).where(auth.StudentProfile.student_number == student_number))
    if duplicate_number:
        raise RuntimeError("门禁学号已被其他学生身份占用")
    session.add(
        auth.StudentProfile(
            student_id=student_id,
            user_id=user_id,
            student_number=student_number,
            full_name=full_name,
            phone=None,
            email=None,
            status="ACTIVE",
            created_at=stamp,
            updated_at=stamp,
        )
    )
