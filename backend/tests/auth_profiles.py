"""测试中的权威账号/学生档案准备工具，不改变生产身份解析路径。"""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.auth import models as auth


ROLE_IDS = {"admin": "role_admin", "teacher": "role_teacher", "student": "role_student"}


def _identifier(kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"yueke-test:{kind}:{value}"))


def seed_reference_roles(session) -> None:
    stamp = datetime.utcnow()
    for code, role_id in ROLE_IDS.items():
        if not session.get(auth.AuthRole, role_id):
            session.add(auth.AuthRole(role_id=role_id, code=code, name={"admin": "管理员", "teacher": "教师", "student": "学生"}[code], created_at=stamp))
    session.flush()


def seed_student_profile(
    session,
    *,
    student_number: str,
    full_name: str,
    student_id: str | None = None,
    status: str = "ACTIVE",
    phone: str | None = None,
    email: str | None = None,
):
    """创建或返回学生权威档案；同学号始终复用同一 student_id。"""

    seed_reference_roles(session)
    existing = session.scalar(select(auth.StudentProfile).where(auth.StudentProfile.student_number == student_number))
    if existing:
        return existing
    stamp = datetime.utcnow()
    user_id = _identifier("user", student_number)
    resolved_student_id = student_id or _identifier("student", student_number)
    session.add(
        auth.AuthUser(
            user_id=user_id,
            external_subject=None,
            login_name=f"test-{student_number}",
            display_name=full_name,
            status=status,
            primary_role_code="student",
            created_at=stamp,
            updated_at=stamp,
        )
    )
    session.add(auth.AuthUserRole(auth_user_role_id=_identifier("user-role", student_number), user_id=user_id, role_id=ROLE_IDS["student"], assigned_at=stamp))
    profile = auth.StudentProfile(
        student_id=resolved_student_id,
        user_id=user_id,
        student_number=student_number,
        full_name=full_name,
        phone=phone,
        email=email,
        status=status,
        created_at=stamp,
        updated_at=stamp,
    )
    session.add(profile)
    session.flush()
    return profile


def seed_student_profiles(sessions, rows) -> None:
    """为 XLSX 测试行预置已有学生档案；危险/空白行不会被伪造为档案。"""

    with sessions() as session:
        for row in rows:
            if len(row) < 2:
                continue
            number, name = str(row[0] or "").strip(), str(row[1] or "").strip()
            if not number or not name or number.startswith(("=", "+", "-", "@")):
                continue
            seed_student_profile(
                session,
                student_number=number,
                full_name=name,
                phone=str(row[3] or "") or None if len(row) > 3 else None,
                email=str(row[4] or "") or None if len(row) > 4 else None,
            )
        session.commit()
