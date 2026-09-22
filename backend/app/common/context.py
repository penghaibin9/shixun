from dataclasses import dataclass
from inspect import isawaitable
from os import getenv
from typing import Annotated, Literal, Protocol

from fastapi import Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import models as auth_models
from app.database import get_session

from .errors import ApiError


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    role: str
    teacher_id: str | None
    student_id: str | None
    permissions: frozenset[str]
    course_ids: frozenset[str]
    class_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class TrustedIdentity:
    """认证层已验证的主体；范围和权限仍必须从本库重新解析。"""

    user_id: str | None = None
    external_subject: str | None = None

    def __post_init__(self) -> None:
        if bool(self.user_id) == bool(self.external_subject):
            raise ValueError("可信身份必须且只能提供 user_id 或 external_subject")


class TrustedIdentityResolver(Protocol):
    """生产认证适配点，由受信任的 SSO/反向代理中间件实现。"""

    def resolve(self, request: Request) -> TrustedIdentity | None: ...


class RequestStateTrustedIdentityResolver:
    """默认桥接：仅消费上游可信 ASGI 中间件已写入的主体。"""

    def resolve(self, request: Request) -> TrustedIdentity | None:
        identity = getattr(request.state, "trusted_identity", None)
        return identity if isinstance(identity, TrustedIdentity) else None


class UserContextResponse(BaseModel):
    user_id: str
    role: Literal["teacher", "student", "admin"]
    teacher_id: str | None
    student_id: str | None
    permissions: list[str]
    course_ids: list[str]
    class_ids: list[str]


def configure_trusted_identity_resolver(app, resolver: TrustedIdentityResolver | None) -> None:
    """注册部署侧认证适配器；本仓库不提供生产凭据或登录方案。"""

    app.state.trusted_identity_resolver = resolver


async def resolve_trusted_identity(request: Request) -> None:
    resolver = getattr(request.app.state, "trusted_identity_resolver", None)
    if resolver is None:
        return
    resolved = resolver.resolve(request)
    if isawaitable(resolved):
        resolved = await resolved
    if resolved is not None and not isinstance(resolved, TrustedIdentity):
        raise RuntimeError("可信身份解析器必须返回 TrustedIdentity 或 None")
    if resolved is not None:
        request.state.trusted_identity = resolved


def _split(value: str | None) -> frozenset[str]:
    return frozenset(item.strip() for item in (value or "").split(",") if item.strip())


def development_headers_allowed() -> bool:
    """开发身份头默认关闭，只有显式测试/开发环境才能打开。"""

    environment = getenv("YUEKE_ENV", "").strip().lower()
    return environment in {"development", "test"} and getenv("YUEKE_ALLOW_DEV_IDENTITY_HEADERS", "") == "1"


def resolve_development_identity_headers(request: Request) -> None:
    """仅供显式本地测试的适配器，避免把伪造头暴露为公开接口契约。"""

    if not development_headers_allowed() or getattr(request.state, "trusted_identity", None):
        return
    user_id = request.headers.get("X-User-Id")
    role = request.headers.get("X-Role")
    if not user_id or role not in {"teacher", "student", "admin"}:
        return
    request.state.user_context = UserContext(
        user_id,
        role,
        request.headers.get("X-Teacher-Id"),
        request.headers.get("X-Student-Id"),
        _split(request.headers.get("X-Permissions")),
        _split(request.headers.get("X-Course-Ids")),
        _split(request.headers.get("X-Class-Ids")),
    )


def _authoritative_context(session: Session, identity: TrustedIdentity) -> UserContext:
    user_stmt = select(auth_models.AuthUser)
    if identity.user_id:
        user_stmt = user_stmt.where(auth_models.AuthUser.user_id == identity.user_id)
    else:
        user_stmt = user_stmt.where(auth_models.AuthUser.external_subject == identity.external_subject)
    user = session.scalar(user_stmt)
    if not user or user.status != "ACTIVE":
        raise ApiError("AUTH.UNAUTHENTICATED", "可信身份未关联有效账号", 401)
    if user.primary_role_code not in {"teacher", "student", "admin"}:
        raise ApiError("AUTH.ROLE_INVALID", "账号角色配置无效", 401)
    role = session.scalar(select(auth_models.AuthRole).where(auth_models.AuthRole.code == user.primary_role_code))
    assigned = session.scalar(
        select(auth_models.AuthUserRole).where(
            auth_models.AuthUserRole.user_id == user.user_id,
            auth_models.AuthUserRole.role_id == (role.role_id if role else ""),
        )
    )
    if not role or not assigned:
        raise ApiError("AUTH.ROLE_INVALID", "账号角色关联无效", 401)
    permissions = frozenset(
        session.scalars(
            select(auth_models.AuthPermission.code)
            .join(auth_models.AuthRolePermission, auth_models.AuthRolePermission.permission_id == auth_models.AuthPermission.permission_id)
            .where(auth_models.AuthRolePermission.role_id == role.role_id)
        )
    )

    # 教学事实仍由 A 所有；这里只在请求期计算范围，不创建第二套范围表。
    from app.teaching import models as teaching_models

    teacher_id: str | None = None
    student_id: str | None = None
    course_ids: set[str] = set()
    class_ids: set[str] = set()
    if user.primary_role_code == "teacher":
        profile = session.scalar(
            select(auth_models.TeacherProfile).where(
                auth_models.TeacherProfile.user_id == user.user_id,
                auth_models.TeacherProfile.status == "ACTIVE",
            )
        )
        if not profile:
            raise ApiError("AUTH.TEACHER_PROFILE_REQUIRED", "可信身份未关联可用教师档案", 401)
        teacher_id = profile.teacher_id
        course_ids.update(session.scalars(select(teaching_models.Course.course_id).where(teaching_models.Course.owner_teacher_id == teacher_id)))
        assignments = session.execute(
            select(teaching_models.TeachingTeacherAssignment.course_id, teaching_models.TeachingTeacherAssignment.class_id).where(
                teaching_models.TeachingTeacherAssignment.teacher_id == teacher_id
            )
        )
        for course_id, class_id in assignments:
            course_ids.add(course_id)
            class_ids.add(class_id)
    elif user.primary_role_code == "student":
        profile = session.scalar(
            select(auth_models.StudentProfile).where(
                auth_models.StudentProfile.user_id == user.user_id,
                auth_models.StudentProfile.status == "ACTIVE",
            )
        )
        if not profile:
            raise ApiError("AUTH.STUDENT_PROFILE_REQUIRED", "可信身份未关联可用学生档案", 401)
        student_id = profile.student_id
        class_ids.update(
            session.scalars(
                select(teaching_models.ClassMembership.class_id).where(
                    teaching_models.ClassMembership.student_id == student_id,
                    teaching_models.ClassMembership.status == "ACTIVE",
                )
            )
        )
        if class_ids:
            course_ids.update(
                session.scalars(select(teaching_models.ClassCourse.course_id).where(teaching_models.ClassCourse.class_id.in_(class_ids)))
            )
    return UserContext(user.user_id, user.primary_role_code, teacher_id, student_id, permissions, frozenset(course_ids), frozenset(class_ids))


async def get_user_context(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserContext:
    # 仅允许部署侧可信中间件注入完整上下文，以兼容已有受控集成。
    existing = getattr(request.state, "user_context", None)
    if isinstance(existing, UserContext):
        return existing
    identity = getattr(request.state, "trusted_identity", None)
    if isinstance(identity, TrustedIdentity):
        context = _authoritative_context(session, identity)
        request.state.user_context = context
        return context
    if development_headers_allowed():
        raise ApiError("AUTH.UNAUTHENTICATED", "未提供有效身份", 401)
    raise ApiError("AUTH.TRUSTED_IDENTITY_REQUIRED", "当前环境只接受认证中间件注入的可信身份", 401)


CurrentUser = Annotated[UserContext, Depends(get_user_context)]
