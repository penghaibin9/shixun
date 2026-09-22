"""正式 MySQL/Nginx 审核启动配置的真实 Linux Docker 门禁。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from node_agent.app import (
    ExecSpec,
    GroupSpec,
    MYSQL_84_DIGEST,
    NGINX_127_DIGEST,
    container_name,
    network_name,
)


PYTHON_DIGEST = "sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca"
AGENT_URL = os.getenv("YUEKE_SERVICE_PROFILE_GATE_URL", "http://127.0.0.1:19444")


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, timeout=30, check=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def agent_request(method: str, path: str, payload: dict | None = None, *, expected_status: int = 200) -> dict:
    token = os.environ.get("YUEKE_NODE_AGENT_TOKEN", "")
    require(bool(token), "节点代理门禁令牌未配置")
    with httpx.Client(base_url=AGENT_URL, timeout=165) as client:
        response = client.request(method, path, headers={"Authorization": f"Bearer {token}"}, json=payload)
    require(response.status_code == expected_status, f"节点代理 {path} 返回 {response.status_code}: {response.text[:500]}")
    return response.json()


def group_spec(group_id: str, target_key: str, target_digest: str, target_memory_mb: int) -> GroupSpec:
    return GroupSpec.model_validate(
        {
            "runtime_group_id": group_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            "networks": [
                {
                    "network_key": "lab-net",
                    "cidr_policy": "AUTO_PRIVATE_24",
                    "internet_access": False,
                    "egress_allowlist": [],
                    "student_isolation": True,
                }
            ],
            "containers": [
                {
                    "node_key": "student-gate",
                    "role": "STUDENT_WORKSTATION",
                    "image_digest": PYTHON_DIGEST,
                    "cpu_limit": 0.5,
                    "memory_mb": 256,
                    "pids_limit": 64,
                    "startup_command": "",
                    "network_keys": ["lab-net"],
                },
                {
                    "node_key": target_key,
                    "role": "TARGET",
                    "image_digest": target_digest,
                    "cpu_limit": 1,
                    "memory_mb": target_memory_mb,
                    "pids_limit": 128,
                    "startup_command": "",
                    "network_keys": ["lab-net"],
                },
            ],
        }
    )


def inspect_security(group_id: str, node_key: str, digest: str, profile_id: str) -> dict:
    name = container_name(group_id, node_key)
    inspected = docker("inspect", name)
    require(inspected.returncode == 0, f"容器不存在：{name}")
    detail = json.loads(inspected.stdout)[0]
    host = detail["HostConfig"]
    config = detail["Config"]
    require(detail["Image"] == digest, f"{node_key} 未使用冻结摘要")
    require(config["Labels"].get("io.yueke.startup-profile") == profile_id, f"{node_key} 启动配置标签错误")
    require(host["Privileged"] is False, f"{node_key} 不得 privileged")
    require(host["NetworkMode"] != "host", f"{node_key} 不得使用 host network")
    require(host["PidMode"] != "host" and host["IpcMode"] != "host", f"{node_key} 不得共享 host PID/IPC")
    require(host["ReadonlyRootfs"] is True, f"{node_key} 根文件系统必须只读")
    require("ALL" in (host.get("CapDrop") or []), f"{node_key} 必须丢弃全部 Linux capabilities")
    require("no-new-privileges:true" in (host.get("SecurityOpt") or []), f"{node_key} 必须禁止权限提升")
    require(not host.get("Binds"), f"{node_key} 不得使用 hostPath/bind mount")
    require(config.get("User") not in {"", "0", "0:0", "root"}, f"{node_key} 必须使用非 root 用户")
    require("/var/run/docker.sock" not in inspected.stdout, f"{node_key} 不得挂载 Docker socket")
    require(all(mount.get("Type") != "bind" for mount in detail.get("Mounts", [])), f"{node_key} 不得存在 bind mount")
    environment = set(config.get("Env") or [])
    tmpfs_paths = set((host.get("Tmpfs") or {}).keys())
    if profile_id == "mysql-8.4-formal-v1":
        require(config.get("Entrypoint") == ["docker-entrypoint.sh"], "MySQL 必须使用审核镜像入口")
        require(config.get("Cmd") == ["mysqld", "--skip-name-resolve", "--bind-address=0.0.0.0"], "MySQL 必须使用审核启动参数")
        require(
            {value for value in environment if value.startswith("MYSQL_")} == {
                "MYSQL_RANDOM_ROOT_PASSWORD=yes", "MYSQL_DATABASE=yueke_lab", "MYSQL_MAJOR=8.4",
                "MYSQL_VERSION=8.4.11-1.el9", "MYSQL_SHELL_VERSION=8.4.10-1.el9",
            },
            "MySQL 审核环境变量必须精确匹配",
        )
        require({"/workspace", "/var/lib/mysql", "/var/run/mysqld", "/tmp"} <= tmpfs_paths, "MySQL 审核 tmpfs 不完整")
    else:
        expected_start = "printf '%s' \"$YUEKE_NGINX_CONFIG\" > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'"
        require(config.get("Entrypoint") == ["/bin/sh"] and config.get("Cmd") == ["-ec", expected_start], "Nginx 必须使用审核入口和命令")
        require(any(value.startswith("YUEKE_NGINX_CONFIG=") and "listen 8080" in value for value in environment), "Nginx 审核配置缺失")
        require({"/workspace", "/var/cache/nginx", "/tmp"} <= tmpfs_paths, "Nginx 审核 tmpfs 不完整")
    return {
        "image_digest": detail["Image"],
        "startup_profile": profile_id,
        "user": config["User"],
        "privileged": host["Privileged"],
        "read_only_rootfs": host["ReadonlyRootfs"],
        "cap_drop": host["CapDrop"],
        "security_opt": host["SecurityOpt"],
        "network_mode": host["NetworkMode"],
        "bind_mounts": host.get("Binds") or [],
    }


def assert_internal_network(group_id: str) -> None:
    inspected = docker("network", "inspect", network_name(group_id, "lab-net"))
    require(inspected.returncode == 0, "实例隔离网络不存在")
    detail = json.loads(inspected.stdout)[0]
    require(detail["Internal"] is True, "实例网络必须是 internal 隔离网络")
    require(detail["Labels"].get("io.yueke.runtime-group") == group_id, "实例网络归属标签错误")


def assert_clean(group_id: str) -> None:
    containers = docker("ps", "-a", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{.ID}}")
    networks = docker("network", "ls", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{.ID}}")
    require(containers.returncode == 0, f"无法核验实例组 {group_id} 的残留容器")
    require(networks.returncode == 0, f"无法核验实例组 {group_id} 的残留网络")
    require(not containers.stdout.strip(), f"实例组 {group_id} 遗留容器")
    require(not networks.stdout.strip(), f"实例组 {group_id} 遗留网络")


def main() -> None:
    suffix = uuid4().hex[:8]
    mysql_group = f"svc-mysql-{suffix}"
    nginx_group = f"svc-nginx-{suffix}"
    raw_group = f"svc-raw-{suffix}"
    evidence: dict[str, object] = {}
    try:
        raw_spec = group_spec(raw_group, "target-raw", NGINX_127_DIGEST, 256)
        raw_spec.containers[1].startup_command = "nginx -g 'daemon off;'"
        agent_request("POST", "/runtime-groups", raw_spec.model_dump(mode="json"), expected_status=422)
        assert_clean(raw_group)

        mysql_spec = group_spec(mysql_group, "target-lab08", MYSQL_84_DIGEST, 1024)
        mysql_payload = mysql_spec.model_dump(mode="json")
        with ThreadPoolExecutor(max_workers=2) as executor:
            mysql_states = list(executor.map(lambda _: agent_request("POST", "/runtime-groups", mysql_payload, expected_status=201), range(2)))
        mysql_state, mysql_retry = mysql_states
        require(mysql_state["status"] == "RUNNING", "MySQL 实例组未运行")
        require(
            {item["container_id"] for item in mysql_retry["containers"]} == {item["container_id"] for item in mysql_state["containers"]},
            "同规格幂等重试不应重建容器",
        )
        changed_mysql_spec = group_spec(mysql_group, "target-lab08", MYSQL_84_DIGEST, 1536)
        agent_request("POST", "/runtime-groups", changed_mysql_spec.model_dump(mode="json"), expected_status=409)
        unsupported_network_spec = group_spec(mysql_group, "target-lab08", MYSQL_84_DIGEST, 1024)
        unsupported_network_spec.networks[0].internet_access = True
        agent_request("POST", "/runtime-groups", unsupported_network_spec.model_dump(mode="json"), expected_status=422)
        assert_internal_network(mysql_group)
        evidence["mysql_security"] = inspect_security(mysql_group, "target-lab08", MYSQL_84_DIGEST, "mysql-8.4-formal-v1")
        mysql_judge = agent_request(
            "POST",
            f"/runtime-groups/{mysql_group}/exec",
            ExecSpec.model_validate(
                {
                    "operation": "judge",
                    "checkpoint": {
                        "checkpoint_id": "cp_lab08_port_gate",
                        "judge_target": "target-lab08:3306",
                        "judge_type": "PORT_LISTEN",
                        "judge_config_json": {"host": "target-lab08", "port": 3306},
                        "failure_message": "MySQL 端口未监听",
                    },
                    "timeout_seconds": 15,
                    "output_limit_bytes": 2048,
                }
            ).model_dump(mode="json"),
        )
        require(mysql_judge["passed"], f"MySQL 3306 真实端口判定失败：{mysql_judge}")
        evidence["mysql_port_3306"] = mysql_judge

        nginx_state = agent_request("POST", "/runtime-groups", group_spec(nginx_group, "target-lab12", NGINX_127_DIGEST, 256).model_dump(mode="json"), expected_status=201)
        require(nginx_state["status"] == "RUNNING", "Nginx 实例组未运行")
        assert_internal_network(nginx_group)
        evidence["nginx_security"] = inspect_security(nginx_group, "target-lab12", NGINX_127_DIGEST, "nginx-1.27-formal-v1")
        nginx_judge = agent_request(
            "POST",
            f"/runtime-groups/{nginx_group}/exec",
            ExecSpec.model_validate(
                {
                    "operation": "judge",
                    "checkpoint": {
                        "checkpoint_id": "cp_lab12_http_gate",
                        "judge_target": "target-lab12:/health",
                        "judge_type": "HTTP_RESPONSE",
                        "judge_config_json": {"path": "/health", "status_code": 200},
                        "failure_message": "Nginx 健康页响应异常",
                    },
                    "timeout_seconds": 15,
                    "output_limit_bytes": 2048,
                }
            ).model_dump(mode="json"),
        )
        require(nginx_judge["passed"], f"Nginx /health 真实网页判定失败：{nginx_judge}")
        evidence["nginx_health_200"] = nginx_judge
    finally:
        for group_id in (mysql_group, nginx_group, raw_group):
            try:
                agent_request("POST", f"/runtime-groups/{group_id}/destroy")
            except (RuntimeError, httpx.HTTPError):
                pass
        for group_id in (mysql_group, nginx_group, raw_group):
            assert_clean(group_id)
    evidence["raw_startup_command_rejected"] = True
    evidence["exact_idempotency_enforced"] = True
    evidence["cleanup_no_residue"] = True
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
