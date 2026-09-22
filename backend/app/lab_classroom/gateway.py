from dataclasses import dataclass
from os import getenv
from typing import Any

import httpx

from app.common.context import UserContext
from app.common.errors import ApiError


# E exposes business permissions while D/A/F enforce their own frozen permissions.
# Translate only the capability that the already-authorized E operation needs; never
# forward a blanket service/admin permission to a downstream service.
DOWNSTREAM_PERMISSION_MAP: dict[str, frozenset[str]] = {
    "classroom.release.read": frozenset({"runtime.read", "teaching.members.read"}),
    "classroom.runtime.remind": frozenset({"runtime.read", "runtime.remind"}),
    "classroom.runtime.rejudge": frozenset({"runtime.read", "runtime.rejudge"}),
    "classroom.runtime.extend": frozenset({"runtime.read", "runtime.extend"}),
    "classroom.runtime.unlock": frozenset({"runtime.read", "runtime.unlock"}),
    "classroom.runtime.rebuild": frozenset({"runtime.read", "runtime.rebuild"}),
    "classroom.runtime.destroy": frozenset({"runtime.read", "runtime.destroy"}),
    "classroom.release.extend-all": frozenset({"runtime.read", "runtime.extend"}),
    "classroom.release.remind-idle": frozenset({"runtime.read", "runtime.remind"}),
    "classroom.lab.start": frozenset({"runtime.read", "runtime.start", "teaching.members.read"}),
    "classroom.lab.read": frozenset({"runtime.read", "teaching.members.read"}),
    "classroom.lab.submit": frozenset({"runtime.read", "runtime.submit", "teaching.members.read"}),
    "classroom.terminal.use": frozenset({"runtime.read", "runtime.terminal"}),
    "classroom.terminal.assist": frozenset({"runtime.read", "runtime.terminal"}),
    "classroom.logs.read": frozenset({"runtime.read", "audit:read"}),
    "classroom.logs.download": frozenset({"runtime.read"}),
    "classroom.logs.distribute": frozenset({"runtime.read", "teaching.members.read"}),
    "classroom.logs.assignment.download": frozenset({"runtime.read"}),
    "classroom.readmodel.read": frozenset({"teaching.members.read", "grading:read"}),
}


def downstream_headers(user: UserContext) -> dict[str, str]:
    permissions = set(user.permissions)
    for permission in user.permissions:
        permissions.update(DOWNSTREAM_PERMISSION_MAP.get(permission, ()))
    return {
        "X-User-Id": user.user_id,
        "X-Role": user.role,
        "X-Teacher-Id": user.teacher_id or "",
        "X-Student-Id": user.student_id or "",
        "X-Permissions": ",".join(sorted(permissions)),
        "X-Course-Ids": ",".join(sorted(user.course_ids)),
        "X-Class-Ids": ",".join(sorted(user.class_ids)),
        "X-Service-Origin": "lab-classroom",
    }


class ContractClient:
    def __init__(self, name: str, base_url: str | None):
        self.name, self.base_url = name, (base_url or "").rstrip("/")

    def request(self, method: str, path: str, user: UserContext, *, params=None, json=None) -> Any:
        if not self.base_url:
            raise ApiError("DEPENDENCY.PENDING", f"{self.name} 服务尚未接入", 503, {"dependency": self.name, "status": "PENDING"})
        try:
            response = httpx.request(method, f"{self.base_url}{path}", headers=downstream_headers(user), params=params, json=json, timeout=8.0)
        except httpx.HTTPError as exc:
            raise ApiError("DEPENDENCY.UNAVAILABLE", f"{self.name} 服务暂不可用", 503, {"dependency": self.name}) from exc
        if response.status_code >= 500:
            raise ApiError("DEPENDENCY.UNAVAILABLE", f"{self.name} 服务暂不可用", 503, {"dependency": self.name, "upstream_status": response.status_code})
        if response.status_code >= 400:
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise ApiError(body.get("code", "DEPENDENCY.REJECTED"), body.get("message", f"{self.name} 拒绝请求"), response.status_code, body.get("details", {}))
        return response.json()


@dataclass(slots=True)
class GatewayBundle:
    runtime: ContractClient
    teaching: ContractClient
    grading: ContractClient


def get_gateways() -> GatewayBundle:
    return GatewayBundle(
        runtime=ContractClient("D 实验运行", getenv("YUEKE_RUNTIME_BASE_URL")),
        teaching=ContractClient("A 教学核心", getenv("YUEKE_TEACHING_BASE_URL")),
        grading=ContractClient("F 成绩审计", getenv("YUEKE_GRADING_BASE_URL")),
    )
