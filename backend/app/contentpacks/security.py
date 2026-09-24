from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SecurityFinding:
    code: str
    message: str
    service: str | None = None
    blocking: bool = True


def _volume_source(value: Any) -> str | None:
    if isinstance(value, str):
        return value.split(":", 1)[0]
    if isinstance(value, dict):
        source = value.get("source")
        return str(source) if source else None
    return None


def scan_compose_manifest(compose: dict[str, Any]) -> list[SecurityFinding]:
    """Static intake guard for third-party lab compose manifests.

    This scanner never executes Docker. Third-party environments must first be
    normalized into Yueke LabDefinition and pass D-line runtime policy.
    """
    findings: list[SecurityFinding] = []
    services = compose.get("services")
    if not isinstance(services, dict):
        return [SecurityFinding("COMPOSE.SERVICES_REQUIRED", "缺少 services 定义")]

    for service_name, raw in services.items():
        service = raw if isinstance(raw, dict) else {}
        if service.get("privileged") is True:
            findings.append(SecurityFinding("COMPOSE.PRIVILEGED", "禁止 privileged 容器", service_name))
        if service.get("network_mode") == "host":
            findings.append(SecurityFinding("COMPOSE.HOST_NETWORK", "禁止 host network", service_name))
        if service.get("pid") == "host":
            findings.append(SecurityFinding("COMPOSE.HOST_PID", "禁止 host PID", service_name))
        if service.get("ipc") == "host":
            findings.append(SecurityFinding("COMPOSE.HOST_IPC", "禁止 host IPC", service_name))
        if service.get("devices"):
            findings.append(SecurityFinding("COMPOSE.DEVICES", "第三方实验禁止直接映射宿主设备", service_name))

        for cap in service.get("cap_add") or []:
            if str(cap).upper() not in {"NET_RAW"}:
                findings.append(
                    SecurityFinding(
                        "COMPOSE.CAPABILITY",
                        f"未批准的 Linux capability: {cap}",
                        service_name,
                    )
                )

        for volume in service.get("volumes") or []:
            source = _volume_source(volume)
            if not source:
                continue
            normalized = source.replace("\\", "/").lower()
            if "docker.sock" in normalized:
                findings.append(SecurityFinding("COMPOSE.DOCKER_SOCKET", "禁止挂载 Docker Socket", service_name))
            elif source.startswith("/") or (len(source) >= 3 and source[1:3] in {":\\", ":/"}):
                findings.append(
                    SecurityFinding(
                        "COMPOSE.HOST_PATH",
                        f"禁止直接挂载宿主绝对路径: {source}",
                        service_name,
                    )
                )

    return findings
