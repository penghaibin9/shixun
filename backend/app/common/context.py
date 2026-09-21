from dataclasses import dataclass
from os import getenv
from typing import Annotated, Literal

from fastapi import Depends, Header, Request
from pydantic import BaseModel

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


class UserContextResponse(BaseModel):
    user_id: str
    role: Literal["teacher", "student", "admin"]
    teacher_id: str | None
    student_id: str | None
    permissions: list[str]
    course_ids: list[str]
    class_ids: list[str]


def _split(value: str | None) -> frozenset[str]:
    return frozenset(item.strip() for item in (value or "").split(",") if item.strip())


async def get_user_context(
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
    x_role: Annotated[str | None, Header()] = None,
    x_teacher_id: Annotated[str | None, Header()] = None,
    x_student_id: Annotated[str | None, Header()] = None,
    x_permissions: Annotated[str | None, Header()] = None,
    x_course_ids: Annotated[str | None, Header()] = None,
    x_class_ids: Annotated[str | None, Header()] = None,
) -> UserContext:
    existing = getattr(request.state, "user_context", None)
    if isinstance(existing, UserContext):
        return existing
    environment = getenv("YUEKE_ENV", "development").strip().lower()
    allow_development_headers = environment in {"development", "test"} and getenv("YUEKE_ALLOW_DEV_IDENTITY_HEADERS", "1") == "1"
    if not allow_development_headers:
        raise ApiError("AUTH.TRUSTED_IDENTITY_REQUIRED", "当前环境只接受认证中间件注入的可信身份", 401)
    if not x_user_id or x_role not in {"teacher", "student", "admin"}:
        raise ApiError("AUTH.UNAUTHENTICATED", "未提供有效身份", 401)
    context = UserContext(x_user_id, x_role, x_teacher_id, x_student_id, _split(x_permissions), _split(x_course_ids), _split(x_class_ids))
    request.state.user_context = context
    return context


CurrentUser = Annotated[UserContext, Depends(get_user_context)]
