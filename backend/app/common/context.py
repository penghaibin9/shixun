from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

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
    if not x_user_id or x_role not in {"teacher", "student", "admin"}:
        raise ApiError("AUTH.UNAUTHENTICATED", "未提供有效身份", 401)
    context = UserContext(x_user_id, x_role, x_teacher_id, x_student_id, _split(x_permissions), _split(x_course_ids), _split(x_class_ids))
    request.state.user_context = context
    return context


CurrentUser = Annotated[UserContext, Depends(get_user_context)]
