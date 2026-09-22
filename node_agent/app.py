"""最小权限 Node Agent；唯一 Docker Engine 操作边界。"""
import asyncio
from contextlib import contextmanager
import json
import math
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import PurePosixPath

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="跃科实验节点代理", docs_url=None, redoc_url=None, openapi_url=None)
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")
SAFE_PATH = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")

APPROVED_COMMANDS: dict[str, tuple[list[str], list[str]]] = {
    "verify_signature": (["openssl", "dgst", "-sha256", "-verify", "public.pem", "-signature", "signature.bin", "source.txt"], ["public.pem", "signature.bin", "source.txt"]),
    "verify_lab01": (["/bin/sh", "-c", "test -s work/cipher.bin && test -s work/plain.out"], ["work/cipher.bin", "work/plain.out"]),
    "verify_lab02": (["/bin/sh", "-c", "test -s work/ecb.bin && test -s work/cbc.bin && test -s work/comparison.json"], ["work/ecb.bin", "work/cbc.bin", "work/comparison.json"]),
    "verify_lab04": (["/bin/sh", "-c", "test -s work/signature.bin && test -s work/verify-original.txt && test -s work/verify-tampered.txt"], ["work/signature.bin", "work/verify-original.txt", "work/verify-tampered.txt"]),
    "verify_lab05": (["/bin/sh", "-c", "test -s work/original.sha256 && test -s work/changed.sha256 && test -s work/integrity-report.json"], ["work/original.sha256", "work/changed.sha256", "work/integrity-report.json"]),
    "verify_lab06": (["/bin/sh", "-c", "test -s work/encoded.txt && test -s work/decoded.txt && test -s work/report.json"], ["work/encoded.txt", "work/decoded.txt", "work/report.json"]),
    "verify_lab07": (["/bin/sh", "-c", "test -s work/carrier.ppm && test -s work/stego.ppm && test -s work/extracted.txt"], ["work/carrier.ppm", "work/stego.ppm", "work/extracted.txt"]),
    "verify_lab08": (["/bin/sh", "-c", "test -s sql/schema.sql && test -s sql/roles.sql"], ["sql/schema.sql", "sql/roles.sql"]),
    "verify_lab09": (["/bin/sh", "-c", "test -s work/masked.csv && test -s work/report.json"], ["work/masked.csv", "work/report.json"]),
    "verify_lab10": (["/bin/sh", "-c", "test -s work/full.zip && test -s work/incremental.json && test -s work/restored/records.json"], ["work/full.zip", "work/incremental.json", "work/restored/records.json"]),
    "verify_lab11": (["/bin/sh", "-c", "test -s work/alerts.json && test -s work/summary.json"], ["work/alerts.json", "work/summary.json"]),
    "verify_lab12": (["/bin/sh", "-c", "test -s work/remediation.csv && test -s work/summary.json"], ["work/remediation.csv", "work/summary.json"]),
}

MYSQL_84_DIGEST = "sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb"
NGINX_127_DIGEST = "sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
NGINX_127_CONFIG = """pid /tmp/nginx.pid;
error_log stderr notice;
events {}
http {
  access_log /dev/stdout;
  server {
    listen 8080;
    location = /health { access_log off; default_type text/plain; return 200 'ok\\n'; }
    location / { root /usr/share/nginx/html; index index.html; }
  }
}
"""
NGINX_127_START = "printf '%s' \"$YUEKE_NGINX_CONFIG\" > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'"

# 启动配置只按冻结镜像摘要选择，实验定义不能注入入口点、命令、环境变量或挂载。
AUDITED_RUNTIME_PROFILES: dict[str, dict] = {
    MYSQL_84_DIGEST: {
        "profile_id": "mysql-8.4-formal-v1",
        "required_role": "TARGET",
        "minimum_memory_mb": 768,
        "user": "999:999",
        "environment": ["MYSQL_RANDOM_ROOT_PASSWORD=yes", "MYSQL_DATABASE=yueke_lab"],
        "mysql_image_environment": ["MYSQL_MAJOR=8.4", "MYSQL_VERSION=8.4.11-1.el9", "MYSQL_SHELL_VERSION=8.4.10-1.el9"],
        "tmpfs": [
            "/workspace:rw,exec,nosuid,size=64m,uid=999,gid=999",
            "/var/lib/mysql:rw,nosuid,size=512m,uid=999,gid=999",
            "/var/run/mysqld:rw,noexec,nosuid,size=16m,uid=999,gid=999",
            "/tmp:rw,noexec,nosuid,size=64m,uid=999,gid=999",
        ],
        "entrypoint": None,
        "expected_entrypoint": ["docker-entrypoint.sh"],
        "command": ["mysqld", "--skip-name-resolve", "--bind-address=0.0.0.0"],
        "ready_command": ["mysqladmin", "ping", "-h", "127.0.0.1", "--silent"],
        "service_port": 3306,
        "ready_timeout_seconds": 60,
    },
    NGINX_127_DIGEST: {
        "profile_id": "nginx-1.27-formal-v1",
        "required_role": "TARGET",
        "minimum_memory_mb": 128,
        "user": "65534:65534",
        "environment": [f"YUEKE_NGINX_CONFIG={NGINX_127_CONFIG}"],
        "tmpfs": [
            "/workspace:rw,exec,nosuid,size=64m,uid=65534,gid=65534",
            "/var/cache/nginx:rw,noexec,nosuid,size=32m,uid=65534,gid=65534",
            "/tmp:rw,noexec,nosuid,size=16m,uid=65534,gid=65534",
        ],
        "entrypoint": "/bin/sh",
        "expected_entrypoint": ["/bin/sh"],
        "command": ["-ec", NGINX_127_START],
        "ready_command": ["wget", "-qO-", "http://127.0.0.1:8080/health"],
        "service_port": 8080,
        "ready_timeout_seconds": 20,
    },
}

GENERIC_RUNTIME_PROFILE = {
    "profile_id": "generic-shell-v1",
    "required_role": None,
    "minimum_memory_mb": 128,
    "user": "65534:65534",
    "environment": [],
    "tmpfs": ["/workspace:rw,exec,nosuid,size=64m,uid=65534,gid=65534"],
    "entrypoint": None,
    "expected_entrypoint": None,
    "command": ["sleep", "infinity"],
    "ready_command": None,
    "service_port": None,
    "ready_timeout_seconds": 0,
}

GROUP_PROVISION_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
GROUP_PROVISION_LOCKS_GUARD = threading.Lock()

EVIDENCE_ARCHIVE_SCRIPT = """
import os, stat, sys, tarfile
opened = []
root_fd = os.open('/workspace', os.O_RDONLY | os.O_DIRECTORY)

def open_regular(relative):
    parts = relative.split('/')
    directory_fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)

try:
    total = 0
    for relative in sys.argv[1:]:
        fd = open_regular(relative)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16 * 1024 * 1024:
                raise SystemExit(20)
            total += metadata.st_size
            if total > 32 * 1024 * 1024:
                raise SystemExit(21)
        except BaseException:
            os.close(fd)
            raise
        opened.append((relative, fd, metadata))
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
        for relative, fd, metadata in opened:
            info = tarfile.TarInfo(relative)
            info.size, info.mode, info.mtime = metadata.st_size, 0o600, 0
            with os.fdopen(fd, 'rb', closefd=False) as source:
                archive.addfile(info, source)
finally:
    for _, fd, _ in opened:
        try: os.close(fd)
        except OSError: pass
    os.close(root_fd)
"""


def docker(*args: str, timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], input=input_text, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HTTPException(503, "Docker Engine 不可用或操作超时") from error


def docker_bytes(*args: str, timeout: int = 30, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["docker", *args], input=input_bytes, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HTTPException(503, "Docker Engine 不可用或操作超时") from error


def require_control(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("YUEKE_NODE_AGENT_TOKEN")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(401, "控制面身份校验失败")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NetworkSpec(StrictModel):
    network_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    cidr_policy: str
    internet_access: bool
    egress_allowlist: list[str]
    student_isolation: bool


class ContainerSpec(StrictModel):
    node_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    role: str
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cpu_limit: float = Field(gt=0, le=8)
    memory_mb: int = Field(ge=128, le=16384)
    pids_limit: int = Field(ge=32, le=512)
    startup_command: str = Field(default="", max_length=512)
    network_keys: list[str] = Field(min_length=1, max_length=8)


class GroupSpec(StrictModel):
    runtime_group_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,64}$")
    expires_at: datetime
    networks: list[NetworkSpec] = Field(min_length=1, max_length=16)
    containers: list[ContainerSpec] = Field(min_length=1, max_length=32)


class ExecSpec(StrictModel):
    operation: str
    checkpoint: dict
    timeout_seconds: int = Field(ge=1, le=30)
    output_limit_bytes: int = Field(ge=256, le=8192)


class ImagePullSpec(StrictModel):
    reference: str = Field(pattern=r"^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$", max_length=300)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def allowed_digests() -> set[str]:
    return {x.strip() for x in os.getenv("YUEKE_AGENT_ALLOWED_DIGESTS", "").split(",") if x.strip()}


def grader_image_digest() -> str:
    digest = os.getenv("YUEKE_AGENT_GRADER_DIGEST", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or digest not in allowed_digests():
        raise HTTPException(503, "节点代理未配置独立的固定摘要判题镜像")
    inspected = docker("image", "inspect", digest, "--format", "{{.Id}}")
    if inspected.returncode or inspected.stdout.strip() != digest:
        raise HTTPException(503, "固定摘要判题镜像尚未就绪")
    return digest


def runtime_profile(image_digest: str, role: str, memory_mb: int) -> dict:
    profile = AUDITED_RUNTIME_PROFILES.get(image_digest, GENERIC_RUNTIME_PROFILE)
    required_role = profile["required_role"]
    if required_role and role != required_role:
        raise HTTPException(422, "正式服务镜像只允许用于目标节点")
    if memory_mb < profile["minimum_memory_mb"]:
        raise HTTPException(422, "节点内存不足以运行审核启动配置")
    return profile


def append_runtime_profile(args: list[str], profile: dict) -> None:
    args.extend(["--label", f"io.yueke.startup-profile={profile['profile_id']}"])
    args.extend(["--user", profile["user"]])
    for value in profile["environment"]:
        args.extend(["--env", value])
    for value in profile["tmpfs"]:
        args.extend(["--tmpfs", value])
    if profile["entrypoint"]:
        args.extend(["--entrypoint", profile["entrypoint"]])


def container_matches_spec(group_id: str, item: "ContainerSpec", profile: dict, expires_at: datetime, deadline: float | None = None) -> bool:
    result = docker("inspect", container_name(group_id, item.node_key), timeout=bounded_timeout(deadline))
    if result.returncode:
        return False
    try:
        detail = json.loads(result.stdout)[0]
        config = detail["Config"]
        host = detail["HostConfig"]
        labels = config.get("Labels") or {}
        actual_expiry = datetime.fromisoformat(labels.get("io.yueke.expires-at", "").replace("Z", "+00:00"))
        expected_expiry = expires_at
        if actual_expiry.tzinfo is None:
            actual_expiry = actual_expiry.replace(tzinfo=timezone.utc)
        if expected_expiry.tzinfo is None:
            expected_expiry = expected_expiry.replace(tzinfo=timezone.utc)
        actual_tmpfs = host.get("Tmpfs") or {}
        expected_tmpfs = {value.split(":", 1)[0]: value.split(":", 1)[1] for value in profile["tmpfs"]}
        tmpfs_matches = set(actual_tmpfs) == set(expected_tmpfs) and all(
            set(actual_tmpfs[path].split(",")) == set(options.split(","))
            for path, options in expected_tmpfs.items()
        )
        expected_entrypoint = profile["expected_entrypoint"]
        actual_environment = config.get("Env") or []
        protected_environment_matches = all(
            [value for value in actual_environment if value.startswith(f"{expected.split('=', 1)[0]}=")] == [expected]
            for expected in profile["environment"]
        )
        if profile["profile_id"] == "mysql-8.4-formal-v1":
            protected_environment_matches = protected_environment_matches and {
                value for value in actual_environment if value.startswith("MYSQL_")
            } == set(profile["environment"] + profile["mysql_image_environment"])
        return (
            detail.get("Image") == item.image_digest
            and detail.get("State", {}).get("Status") == "running"
            and labels.get("io.yueke.runtime-group") == group_id
            and labels.get("io.yueke.node-key") == item.node_key
            and labels.get("io.yueke.role") == item.role
            and labels.get("io.yueke.startup-profile") == profile["profile_id"]
            and actual_expiry.astimezone(timezone.utc) == expected_expiry.astimezone(timezone.utc)
            and int(host.get("NanoCpus") or 0) == round(item.cpu_limit * 1_000_000_000)
            and int(host.get("Memory") or 0) == item.memory_mb * 1024 * 1024
            and int(host.get("PidsLimit") or 0) == item.pids_limit
            and config.get("User") == profile["user"]
            and host.get("Privileged") is False
            and host.get("NetworkMode") != "host"
            and host.get("PidMode") != "host"
            and host.get("IpcMode") != "host"
            and host.get("ReadonlyRootfs") is True
            and set(host.get("CapDrop") or []) == {"ALL"}
            and set(host.get("SecurityOpt") or []) == {"no-new-privileges:true"}
            and not host.get("Binds")
            and all(mount.get("Type") != "bind" for mount in detail.get("Mounts", []))
            and protected_environment_matches
            and (expected_entrypoint is None or config.get("Entrypoint") == expected_entrypoint)
            and config.get("Cmd") == profile["command"]
            and tmpfs_matches
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def wait_for_runtime_profile(name: str, profile: dict, provision_deadline: float) -> None:
    ready_command = profile["ready_command"]
    if not ready_command:
        return
    deadline = min(time.monotonic() + profile["ready_timeout_seconds"], provision_deadline)
    while time.monotonic() < deadline:
        state = docker("inspect", "--format", "{{.State.Status}}|{{.State.ExitCode}}", name, timeout=min(5, remaining_timeout(deadline)))
        if state.returncode or not state.stdout.startswith("running|"):
            raise HTTPException(503, "审核启动配置对应的服务容器异常退出")
        probe = docker("exec", name, *ready_command, timeout=min(5, remaining_timeout(deadline)))
        if probe.returncode == 0:
            return
        time.sleep(0.25)
    raise HTTPException(503, "审核启动配置对应的服务未在时限内就绪")


def container_startup_profile(name: str, deadline: float | None = None) -> str:
    result = docker("inspect", "--format", "{{index .Config.Labels \"io.yueke.startup-profile\"}}", name, timeout=bounded_timeout(deadline))
    if result.returncode:
        raise HTTPException(404, "检查点目标容器缺少审核启动配置")
    return result.stdout.strip()


def profile_service_port(profile_id: str) -> int | None:
    for profile in AUDITED_RUNTIME_PROFILES.values():
        if profile["profile_id"] == profile_id:
            return profile["service_port"]
    return None


def container_name(group_id: str, node_key: str) -> str:
    group_token = f"{group_id[:16]}-{sha256(group_id.encode()).hexdigest()[:10]}"
    node_token = f"{node_key[:12]}-{sha256(node_key.encode()).hexdigest()[:8]}"
    return f"yk-{group_token}-{node_token}".lower()


def network_name(group_id: str, key: str) -> str:
    group_token = f"{group_id[:16]}-{sha256(group_id.encode()).hexdigest()[:10]}"
    network_token = f"{key[:12]}-{sha256(key.encode()).hexdigest()[:8]}"
    return f"yk-{group_token}-{network_token}".lower()


def bounded_timeout(deadline: float | None, maximum: int = 30) -> int:
    return maximum if deadline is None else min(maximum, remaining_timeout(deadline))


def docker_object_not_found(result: subprocess.CompletedProcess) -> bool:
    message = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode != 0 and any(marker in message for marker in ("no such object", "no such container", "no such network"))


@contextmanager
def group_operation_lock(group_id: str, deadline: float):
    with GROUP_PROVISION_LOCKS_GUARD:
        lock, references = GROUP_PROVISION_LOCKS.get(group_id, (threading.Lock(), 0))
        GROUP_PROVISION_LOCKS[group_id] = (lock, references + 1)
    acquired = lock.acquire(timeout=max(0.1, deadline - time.monotonic()))
    if not acquired:
        with GROUP_PROVISION_LOCKS_GUARD:
            current_lock, references = GROUP_PROVISION_LOCKS[group_id]
            if references == 1:
                del GROUP_PROVISION_LOCKS[group_id]
            else:
                GROUP_PROVISION_LOCKS[group_id] = (current_lock, references - 1)
        raise HTTPException(503, "实例组正在执行互斥操作，请稍后重试")
    try:
        yield
    finally:
        lock.release()
        with GROUP_PROVISION_LOCKS_GUARD:
            current_lock, references = GROUP_PROVISION_LOCKS[group_id]
            if references == 1:
                del GROUP_PROVISION_LOCKS[group_id]
            else:
                GROUP_PROVISION_LOCKS[group_id] = (current_lock, references - 1)


def group_containers(group_id: str, *, include_graders: bool = False, deadline: float | None = None) -> list[dict]:
    args = ["ps", "-a", "--filter", f"label=io.yueke.runtime-group={group_id}"]
    if not include_graders:
        args.extend(["--filter", "label=io.yueke.node-key"])
    result = docker(*args, "--format", "{{json .}}", timeout=bounded_timeout(deadline))
    if result.returncode:
        raise HTTPException(503, "无法读取容器状态")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def group_network_ids(group_id: str, *, deadline: float | None = None) -> list[str]:
    result = docker("network", "ls", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{.ID}}", timeout=bounded_timeout(deadline))
    if result.returncode:
        raise HTTPException(503, "无法读取实例组网络状态")
    return [network_id.strip() for network_id in result.stdout.splitlines() if network_id.strip()]


def remove_labeled_container(group_id: str, name: str, *, deadline: float | None = None, provision_id: str | None = None) -> None:
    label = docker("inspect", "--format", "{{index .Config.Labels \"io.yueke.runtime-group\"}}|{{index .Config.Labels \"io.yueke.provision-id\"}}", name, timeout=bounded_timeout(deadline))
    if docker_object_not_found(label):
        return
    owner, separator, actual_provision_id = label.stdout.strip().partition("|")
    if label.returncode or owner != group_id or (provision_id is not None and (not separator or actual_provision_id != provision_id)):
        raise HTTPException(503, "无法确认待回收容器的实例组归属")
    removed = docker("rm", "-f", name, timeout=bounded_timeout(deadline))
    if removed.returncode:
        verified = docker("inspect", name, timeout=bounded_timeout(deadline))
        if not docker_object_not_found(verified):
            raise HTTPException(503, "实例组容器未能回收")


def remove_labeled_network(group_id: str, name: str, *, deadline: float | None = None, provision_id: str | None = None) -> None:
    label = docker("network", "inspect", "--format", "{{index .Labels \"io.yueke.runtime-group\"}}|{{index .Labels \"io.yueke.provision-id\"}}", name, timeout=bounded_timeout(deadline))
    if docker_object_not_found(label):
        return
    owner, separator, actual_provision_id = label.stdout.strip().partition("|")
    if label.returncode or owner != group_id or (provision_id is not None and (not separator or actual_provision_id != provision_id)):
        raise HTTPException(503, "无法确认待回收网络的实例组归属")
    removed = docker("network", "rm", name, timeout=bounded_timeout(deadline))
    if removed.returncode:
        verified = docker("network", "inspect", name, timeout=bounded_timeout(deadline))
        if not docker_object_not_found(verified):
            raise HTTPException(503, "实例组网络未能回收")


@app.on_event("startup")
def reconcile_expired_groups() -> None:
    """代理重启时分别回收过期实例组和过期临时判题器。"""
    graders = docker("ps", "-a", "--filter", "label=io.yueke.role=grader", "--filter", "label=io.yueke.grader-expires-at", "--format", "{{.ID}}|{{.Label \"io.yueke.grader-expires-at\"}}", timeout=15)
    current = datetime.now(timezone.utc)
    if graders.returncode == 0:
        for line in graders.stdout.splitlines():
            container_id, _, value = line.partition("|")
            try:
                expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= current:
                    docker("rm", "-f", container_id)
            except ValueError:
                continue
    rows = docker("ps", "-a", "--filter", "label=io.yueke.expires-at", "--format", "{{.Label \"io.yueke.role\"}}|{{.Label \"io.yueke.runtime-group\"}}|{{.Label \"io.yueke.expires-at\"}}", timeout=15)
    if rows.returncode:
        return
    expired: set[str] = set()
    for line in rows.stdout.splitlines():
        role, group_id, value = line.split("|", 2)
        if role == "grader":
            continue
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if SAFE_ID.fullmatch(group_id) and expiry <= current:
                expired.add(group_id)
        except ValueError:
            continue
    for group_id in expired:
        destroy_group(group_id)


@app.get("/health", dependencies=[Depends(require_control)])
def health():
    result = docker("info", "--format", "{{.OSType}} {{.ServerVersion}}", timeout=10)
    if result.returncode or not result.stdout.startswith("linux "):
        raise HTTPException(503, "节点必须连接 Linux Docker Engine")
    return {"status": "ok", "engine": result.stdout.strip()}


@app.get("/capacity", dependencies=[Depends(require_control)])
def capacity():
    info = docker("info", "--format", "{{json .}}", timeout=10)
    if info.returncode:
        raise HTTPException(503, "无法读取节点容量")
    data = json.loads(info.stdout)
    images = docker("image", "ls", "--digests", "--format", "{{.Digest}}")
    running = docker("ps", "--filter", "label=io.yueke.runtime-group", "--format", "{{.ID}}|{{.Label \"io.yueke.runtime-group\"}}")
    containers = [line.split("|", 1) for line in running.stdout.splitlines() if "|" in line]
    groups = {group for _, group in containers if group}
    used_cpu = 0.0
    used_memory_mb = 0
    for container_id, _ in containers:
        limits = docker("inspect", "--format", "{{.HostConfig.NanoCpus}}|{{.HostConfig.Memory}}", container_id)
        if limits.returncode == 0 and "|" in limits.stdout:
            nano, memory = limits.stdout.strip().split("|", 1)
            used_cpu += int(nano or 0) / 1_000_000_000
            used_memory_mb += int(memory or 0) // 1024 // 1024
    cpu_total = float(data.get("NCPU", 0))
    memory_total = int(data.get("MemTotal", 0) / 1024 / 1024)
    return {"engine": f"linux {data.get('ServerVersion')}", "cpu_total": cpu_total, "memory_total_mb": memory_total, "cpu_available": max(cpu_total - used_cpu, 0), "memory_available_mb": max(memory_total - used_memory_mb, 0), "running_groups": len(groups), "image_digests": sorted({x for x in images.stdout.splitlines() if x and x != "<none>"})}


@app.post("/images/pull", dependencies=[Depends(require_control)])
def pull_image(spec: ImagePullSpec):
    if spec.digest not in allowed_digests() or not spec.reference.endswith(f"@{spec.digest}"):
        raise HTTPException(422, "镜像摘要不在节点白名单")
    result = docker("pull", spec.reference, timeout=300)
    if result.returncode:
        raise HTTPException(503, "固定摘要镜像拉取失败")
    inspected = docker("image", "inspect", spec.reference, "--format", "{{.Id}}")
    if inspected.returncode:
        raise HTTPException(503, "镜像摘要校验失败")
    return {"reference": spec.reference, "digest": spec.digest, "status": "READY"}


def create_group_locked(spec: GroupSpec, provision_deadline: float) -> dict:
    if spec.expires_at.replace(tzinfo=None) <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(422, "实例过期时间无效")
    if any(item.startup_command for item in spec.containers):
        raise HTTPException(422, "节点代理不执行实验定义中的原始启动命令")
    if len({item.node_key for item in spec.containers}) != len(spec.containers) or len({item.network_key for item in spec.networks}) != len(spec.networks):
        raise HTTPException(422, "实例组节点或网络标识重复")
    if any(x.internet_access or x.egress_allowlist or not x.student_isolation or x.cidr_policy != "AUTO_PRIVATE_24" for x in spec.networks):
        raise HTTPException(422, "首期节点代理只接受自动私网地址和无外网的学生隔离网络")
    allowed = allowed_digests()
    requested = {item.image_digest for item in spec.containers}
    if not allowed or not requested.issubset(allowed):
        raise HTTPException(422, "镜像摘要不在节点白名单")
    profiles = {
        item.node_key: runtime_profile(item.image_digest, item.role, item.memory_mb)
        for item in spec.containers
    }
    existing_containers = group_containers(spec.runtime_group_id, deadline=provision_deadline)
    if existing_containers:
        existing = inspect_group_state(spec.runtime_group_id, deadline=provision_deadline)
        expected_nodes = {item.node_key for item in spec.containers}
        expected_networks = {item.network_key for item in spec.networks}
        actual_nodes = {item["node_key"] for item in existing["containers"]}
        actual_networks = {item["network_key"] for item in existing["networks"]}
        expected_topology = {item.node_key: set(item.network_keys) for item in spec.containers}
        actual_topology = {item["node_key"]: set(item["network_keys"]) for item in existing["containers"]}
        expected_images = {item.node_key: item.image_digest for item in spec.containers}
        actual_images = {item["node_key"]: item["image_digest"] for item in existing["containers"]}
        expected_profiles = {key: profile["profile_id"] for key, profile in profiles.items()}
        actual_profiles = {item["node_key"]: item["startup_profile"] for item in existing["containers"]}
        exact_container_specs = all(container_matches_spec(spec.runtime_group_id, item, profiles[item.node_key], spec.expires_at, provision_deadline) for item in spec.containers)
        if (
            existing["status"] == "RUNNING"
            and actual_nodes == expected_nodes
            and actual_networks == expected_networks
            and actual_topology == expected_topology
            and actual_images == expected_images
            and actual_profiles == expected_profiles
            and exact_container_specs
        ):
            for item in spec.containers:
                wait_for_runtime_profile(container_name(spec.runtime_group_id, item.node_key), profiles[item.node_key], provision_deadline)
            return existing
        if existing["status"] == "RUNNING":
            raise HTTPException(409, "实例组标识已被不同运行规格占用")
        destroy_group_resources(spec.runtime_group_id, deadline=provision_deadline)
    elif group_network_ids(spec.runtime_group_id, deadline=provision_deadline):
        destroy_group_resources(spec.runtime_group_id, deadline=provision_deadline)
    provision_id = os.urandom(16).hex()
    created_networks = {net.network_key: network_name(spec.runtime_group_id, net.network_key) for net in spec.networks}
    created_containers = [container_name(spec.runtime_group_id, item.node_key) for item in spec.containers]
    try:
        for net in spec.networks:
            name = created_networks[net.network_key]
            result = docker("network", "create", "--internal", "--label", f"io.yueke.runtime-group={spec.runtime_group_id}", "--label", f"io.yueke.network-key={net.network_key}", "--label", f"io.yueke.provision-id={provision_id}", name, timeout=min(30, remaining_timeout(provision_deadline)))
            if result.returncode:
                raise HTTPException(503, "创建隔离网络失败")
        for item in spec.containers:
            requested_networks = [created_networks.get(key) for key in item.network_keys]
            if not requested_networks or any(name is None for name in requested_networks):
                raise HTTPException(422, "场景节点引用了不存在的实例网络")
            primary = requested_networks[0]
            name = container_name(spec.runtime_group_id, item.node_key)
            profile = profiles[item.node_key]
            args = ["run", "-d", "--name", name, "--network", primary, "--network-alias", item.node_key,
                    "--label", f"io.yueke.runtime-group={spec.runtime_group_id}", "--label", f"io.yueke.node-key={item.node_key}",
                    "--label", f"io.yueke.role={item.role}", "--label", f"io.yueke.provision-id={provision_id}",
                    "--label", f"io.yueke.expires-at={spec.expires_at.isoformat()}", "--cpus", str(item.cpu_limit),
                    "--memory", f"{item.memory_mb}m", "--pids-limit", str(item.pids_limit), "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges:true", "--read-only", "--workdir", "/workspace"]
            append_runtime_profile(args, profile)
            args.extend([item.image_digest, *profile["command"]])
            result = docker(*args, timeout=min(60, remaining_timeout(provision_deadline)))
            if result.returncode:
                raise HTTPException(503, "创建受限实验容器失败")
            for extra_network in requested_networks[1:]:
                connected = docker("network", "connect", "--alias", item.node_key, extra_network, name, timeout=min(30, remaining_timeout(provision_deadline)))
                if connected.returncode:
                    raise HTTPException(503, "连接场景节点附加网络失败")
            wait_for_runtime_profile(name, profile, provision_deadline)
        return inspect_group_state(spec.runtime_group_id, deadline=provision_deadline)
    except Exception as creation_error:
        # 创建阶段最多 120 秒；失败后另给回滚一个共享的 30 秒总预算。
        rollback_deadline = time.monotonic() + 30
        rollback_failures: list[str] = []
        for name in created_containers:
            try:
                remove_labeled_container(spec.runtime_group_id, name, deadline=rollback_deadline, provision_id=provision_id)
            except HTTPException:
                rollback_failures.append(f"container:{name}")
        for network_key, name in created_networks.items():
            try:
                remove_labeled_network(spec.runtime_group_id, name, deadline=rollback_deadline, provision_id=provision_id)
            except HTTPException:
                rollback_failures.append(f"network:{network_key}")
        if rollback_failures:
            raise HTTPException(503, f"实例组创建失败且有资源未确认回收：{','.join(rollback_failures)}") from creation_error
        raise


@app.post("/runtime-groups", dependencies=[Depends(require_control)], status_code=201)
def create_group(spec: GroupSpec):
    provision_deadline = time.monotonic() + 120
    with group_operation_lock(spec.runtime_group_id, provision_deadline):
        return create_group_locked(spec, provision_deadline)


def inspect_group_state(group_id: str, *, deadline: float | None = None) -> dict:
    if not SAFE_ID.fullmatch(group_id):
        raise HTTPException(422, "实例组标识无效")
    containers = group_containers(group_id, deadline=deadline)
    networks = docker("network", "ls", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{json .}}", timeout=bounded_timeout(deadline))
    if networks.returncode:
        raise HTTPException(503, "无法读取实例组网络状态")
    network_rows = [json.loads(x) for x in networks.stdout.splitlines() if x.strip()]
    container_rows = []
    for item in containers:
        details = docker("inspect", "--format", "{{index .Config.Labels \"io.yueke.node-key\"}}|{{.Image}}", item["ID"], timeout=bounded_timeout(deadline))
        if details.returncode:
            raise HTTPException(503, "无法读取实例组容器详情")
        node_key, separator, image_digest = details.stdout.strip().partition("|")
        if not separator:
            raise HTTPException(503, "实例组容器详情不完整")
        container_rows.append({
            "container_id": item["ID"],
            "name": item["Names"],
            "node_key": node_key,
            "network_keys": container_group_network_keys(group_id, item["ID"], deadline=deadline),
            "image_digest": image_digest,
            "startup_profile": container_startup_profile(item["ID"], deadline),
        })
    network_details = []
    for item in network_rows:
        details = docker("network", "inspect", "--format", "{{index .Labels \"io.yueke.network-key\"}}", item["ID"], timeout=bounded_timeout(deadline))
        if details.returncode or not details.stdout.strip():
            raise HTTPException(503, "无法读取实例组网络详情")
        network_details.append({
            "network_id": item["ID"],
            "network_key": details.stdout.strip(),
            "isolation_checks": {"business_mysql": "DENY", "other_student": "DENY", "grader": "ALLOW_SAME_GROUP_ONLY"},
        })
    return {
        "provider_group_id": group_id,
        "status": "RUNNING" if containers and all(x.get("State") == "running" for x in containers) else "FAILED",
        "containers": container_rows,
        "networks": network_details,
    }


@app.get("/runtime-groups/{group_id}", dependencies=[Depends(require_control)])
def inspect_group(group_id: str):
    return inspect_group_state(group_id)


def destroy_group_resources(group_id: str, *, deadline: float | None = None) -> dict:
    failures: list[str] = []
    for item in group_containers(group_id, include_graders=True, deadline=deadline):
        removed = docker("rm", "-f", item["ID"], timeout=bounded_timeout(deadline))
        if removed.returncode:
            verified = docker("inspect", item["ID"], timeout=bounded_timeout(deadline))
            if not docker_object_not_found(verified):
                failures.append(item["ID"])
    for network_id in group_network_ids(group_id, deadline=deadline):
        removed = docker("network", "rm", network_id, timeout=bounded_timeout(deadline))
        if removed.returncode:
            verified = docker("network", "inspect", network_id, timeout=bounded_timeout(deadline))
            if not docker_object_not_found(verified):
                failures.append(network_id)
    if failures:
        raise HTTPException(503, "实例组资源未能完整回收")
    return {"provider_group_id": group_id, "status": "DESTROYED"}


@app.post("/runtime-groups/{group_id}/destroy", dependencies=[Depends(require_control)])
def destroy_group(group_id: str):
    if not SAFE_ID.fullmatch(group_id):
        raise HTTPException(422, "实例组标识无效")
    deadline = time.monotonic() + 30
    with group_operation_lock(group_id, deadline):
        return destroy_group_resources(group_id, deadline=deadline)


def safe_file(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or len(value) > 256
        or any(part in {"", ".", ".."} or not SAFE_PATH.fullmatch(part) for part in path.parts)
    ):
        raise HTTPException(422, "检查点文件名不安全")
    return str(path)


def approved_command(command_ref: str) -> list[str]:
    entry = APPROVED_COMMANDS.get(command_ref)
    if not entry:
        raise HTTPException(422, "命令判定标识未获节点代理批准")
    return list(entry[0])


def approved_command_paths(command_ref: str) -> list[str]:
    entry = APPROVED_COMMANDS.get(command_ref)
    if not entry:
        raise HTTPException(422, "命令判定标识未获节点代理批准")
    return [safe_file(path) for path in entry[1]]


def group_container_for_role(group_id: str, role: str) -> str:
    result = docker(
        "ps", "-a",
        "--filter", f"label=io.yueke.runtime-group={group_id}",
        "--filter", f"label=io.yueke.role={role}",
        "--format", "{{.Names}}",
    )
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or len(names) != 1:
        raise HTTPException(404, "实例组缺少唯一的学生操作容器")
    return names[0]


def container_group_network(group_id: str, name: str) -> str:
    result = docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", name)
    if result.returncode:
        raise HTTPException(404, "检查点目标容器网络不存在")
    for network_name in sorted(json.loads(result.stdout or "{}").keys()):
        label = docker("network", "inspect", "--format", "{{index .Labels \"io.yueke.runtime-group\"}}", network_name)
        if label.returncode == 0 and label.stdout.strip() == group_id:
            return network_name
    raise HTTPException(404, "检查点目标容器不在实例组隔离网络")


def container_group_network_keys(group_id: str, name: str, *, deadline: float | None = None) -> list[str]:
    result = docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", name, timeout=bounded_timeout(deadline))
    if result.returncode:
        raise HTTPException(404, "实例组容器网络不存在")
    keys: list[str] = []
    for attached_name in sorted(json.loads(result.stdout or "{}").keys()):
        labels = docker("network", "inspect", "--format", "{{index .Labels \"io.yueke.runtime-group\"}}|{{index .Labels \"io.yueke.network-key\"}}", attached_name, timeout=bounded_timeout(deadline))
        if labels.returncode:
            raise HTTPException(503, "无法核验实例组容器网络")
        owner, _, network_key = labels.stdout.strip().partition("|")
        if owner != group_id or not network_key:
            raise HTTPException(409, "实例组容器连接了未授权网络")
        keys.append(network_key)
    return keys


def checkpoint_target_node(checkpoint: dict) -> str:
    target = str(checkpoint.get("judge_target", ""))
    node_key, separator, _ = target.partition(":")
    if not separator or node_key == "submission" or not SAFE_ID.fullmatch(node_key):
        raise HTTPException(422, "网络检查点目标节点无效")
    return node_key


def checked_group_container(group_id: str, node_key: str) -> str:
    name = container_name(group_id, node_key)
    labels = docker("inspect", "--format", "{{index .Config.Labels \"io.yueke.runtime-group\"}}|{{index .Config.Labels \"io.yueke.node-key\"}}", name)
    if labels.returncode or labels.stdout.strip() != f"{group_id}|{node_key}":
        raise HTTPException(404, "检查点目标容器不存在")
    return name


def checkpoint_evidence_container(group_id: str, checkpoint: dict) -> str:
    target = str(checkpoint.get("judge_target", ""))
    node_key, separator, _ = target.partition(":")
    if node_key == "submission":
        return group_container_for_role(group_id, "STUDENT_WORKSTATION")
    if not separator or not SAFE_ID.fullmatch(node_key):
        raise HTTPException(422, "文件检查点目标节点无效")
    return checked_group_container(group_id, node_key)


def command_evidence_container(group_id: str, command_ref: str) -> str:
    # 经审核的命令只读取学生工作区产物；judge_target 描述验证目标，不能改变证据来源。
    if command_ref not in APPROVED_COMMANDS:
        raise HTTPException(422, "命令判定标识未获节点代理批准")
    return group_container_for_role(group_id, "STUDENT_WORKSTATION")


def remove_owned_container(name: str, evaluation_id: str) -> bool:
    inspected = docker("inspect", "--format", "{{.Id}}|{{index .Config.Labels \"io.yueke.evaluation-id\"}}", name)
    if inspected.returncode:
        return True
    container_id, separator, owner = inspected.stdout.strip().partition("|")
    if not separator or owner != evaluation_id or not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        return False
    docker("rm", "-f", container_id)
    return docker("inspect", container_id).returncode != 0


def remaining_timeout(deadline: float) -> int:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HTTPException(503, "受控操作超时")
    return max(1, math.ceil(remaining))


def collect_evidence(source_name: str, paths: list[str], deadline: float) -> subprocess.CompletedProcess[bytes]:
    if not paths or len(paths) > 16:
        raise HTTPException(422, "检查点证据文件数量无效")
    return docker_bytes(
        "exec", "--user", "65534:65534", source_name,
        "python3", "-c", EVIDENCE_ARCHIVE_SCRIPT, *paths,
        timeout=remaining_timeout(deadline),
    )


@app.post("/runtime-groups/{group_id}/exec", dependencies=[Depends(require_control)])
def execute_checkpoint(group_id: str, spec: ExecSpec):
    if spec.operation != "judge" or not SAFE_ID.fullmatch(group_id):
        raise HTTPException(422, "仅允许受控检查点判定")
    checkpoint = spec.checkpoint
    deadline = time.monotonic() + spec.timeout_seconds
    student_name = group_container_for_role(group_id, "STUDENT_WORKSTATION")
    source_image = docker("inspect", "--format", "{{.Image}}", student_name)
    if source_image.returncode or not source_image.stdout.strip().startswith("sha256:"):
        raise HTTPException(404, "学生操作容器不存在")
    kind = checkpoint.get("judge_type")
    config = checkpoint.get("judge_config_json", {})
    if not isinstance(config, dict):
        raise HTTPException(422, "检查点判定配置无效")
    allowed_config = {
        "FILE_EXISTS": {"path", "additional_paths", "minimum_size", "format"},
        "FILE_HASH": {"left_path", "right_path", "algorithm"},
        "COMMAND_EXIT": {"command_ref", "expected_exit", "output_contains"},
        "PORT_LISTEN": {"host", "port"},
        "HTTP_RESPONSE": {"path", "port", "status_code"},
    }
    if kind in allowed_config and set(config) - allowed_config[kind]:
        raise HTTPException(422, "检查点判定配置包含未批准字段")
    required_paths: list[str] = []
    if kind == "FILE_EXISTS":
        path_value = config.get("path")
        additional_paths = config.get("additional_paths", [])
        minimum_size = config.get("minimum_size", 1)
        if not isinstance(path_value, str) or not isinstance(additional_paths, list) or not all(isinstance(item, str) for item in additional_paths):
            raise HTTPException(422, "文件存在判定路径无效")
        if not isinstance(minimum_size, int) or not 0 <= minimum_size <= 64 * 1024 * 1024:
            raise HTTPException(422, "文件存在判定最小大小无效")
        paths = [safe_file(path_value), *[safe_file(x) for x in additional_paths]]
        required_paths = paths
        command = ["/bin/sh", "-c", " && ".join(f"test -f ./{path} && test $(wc -c < ./{path}) -ge {minimum_size}" for path in paths)]
        if config.get("format") == "PEM":
            if len(paths) != 2:
                raise HTTPException(422, "PEM 文件判定必须提供私钥和公钥两个路径")
            command = ["/bin/sh", "-c", f"test -s ./{paths[0]} && test -s ./{paths[1]} && openssl pkey -in ./{paths[0]} -noout && openssl pkey -pubin -in ./{paths[1]} -noout"]
    elif kind == "FILE_HASH":
        left_value, right_value = config.get("left_path"), config.get("right_path")
        if not isinstance(left_value, str) or not isinstance(right_value, str) or config.get("algorithm") != "sha256":
            raise HTTPException(422, "文件哈希判定配置无效")
        left, right = safe_file(left_value), safe_file(right_value)
        required_paths = [left, right]
        command = ["/bin/sh", "-c", f"test \"$(sha256sum ./{left} | cut -d' ' -f1)\" = \"$(sha256sum ./{right} | cut -d' ' -f1)\""]
    elif kind == "COMMAND_EXIT":
        expected_exit = config.get("expected_exit")
        if not isinstance(expected_exit, int) or not 0 <= expected_exit <= 255:
            raise HTTPException(422, "命令判定退出码无效")
        output_contains = config.get("output_contains")
        if output_contains is not None and (not isinstance(output_contains, str) or len(output_contains) > 512):
            raise HTTPException(422, "命令判定输出条件无效")
        command_ref = str(config.get("command_ref", ""))
        command = approved_command(command_ref)
        required_paths = approved_command_paths(command_ref)
    elif kind == "PORT_LISTEN":
        node_key = str(config.get("host", ""))
        if node_key != checkpoint_target_node(checkpoint):
            raise HTTPException(422, "端口判定主机与目标节点不一致")
        target_name = checked_group_container(group_id, node_key)
        port = config.get("port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise HTTPException(422, "端口判定端口无效")
        host = target_name
        command = ["python3", "-c", "import socket,sys; sock=socket.create_connection((sys.argv[1],int(sys.argv[2])),3); sock.close()", host, str(port)]
    elif kind == "HTTP_RESPONSE":
        node_key = checkpoint_target_node(checkpoint)
        target_name = checked_group_container(group_id, node_key)
        path = config.get("path")
        port = config.get("port")
        if port is None:
            port = profile_service_port(container_startup_profile(target_name)) or 80
        status_code = config.get("status_code")
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 256:
            raise HTTPException(422, "网页响应判定路径无效")
        if not isinstance(port, int) or not 1 <= port <= 65535 or not isinstance(status_code, int) or not 100 <= status_code <= 599:
            raise HTTPException(422, "网页响应判定端口或状态码无效")
        host = target_name
        command = ["python3", "-c", "import http.client,sys; conn=http.client.HTTPConnection(sys.argv[1],int(sys.argv[2]),timeout=3); conn.request('GET',sys.argv[3]); response=conn.getresponse(); raise SystemExit(0 if response.status==int(sys.argv[4]) else 1)", host, str(port), path, str(status_code)]
    else:
        raise HTTPException(422, "检查点类型未获节点代理批准")
    checkpoint_id = str(checkpoint.get("checkpoint_id", "cp"))
    if not SAFE_ID.fullmatch(checkpoint_id):
        raise HTTPException(422, "检查点标识无效")
    group_token = f"{group_id[:16]}-{sha256(group_id.encode()).hexdigest()[:10]}"
    grader_name = f"yk-grader-{group_token}".lower()
    evaluation_id = os.urandom(16).hex()
    needs_files = kind in {"FILE_EXISTS", "FILE_HASH", "COMMAND_EXIT"}
    if kind == "COMMAND_EXIT":
        source_name = command_evidence_container(group_id, command_ref)
    elif needs_files:
        source_name = checkpoint_evidence_container(group_id, checkpoint)
    else:
        source_name = student_name
    grader_network = "none" if needs_files else container_group_network(group_id, target_name)
    grader_expiry = datetime.now(timezone.utc) + timedelta(seconds=spec.timeout_seconds + 30)
    grader_created = False
    try:
        created = docker("create", "--name", grader_name, "--network", grader_network, "--label", f"io.yueke.runtime-group={group_id}",
                         "--label", "io.yueke.role=grader", "--label", f"io.yueke.checkpoint-id={checkpoint_id}",
                         "--label", f"io.yueke.evaluation-id={evaluation_id}", "--label", f"io.yueke.grader-expires-at={grader_expiry.isoformat()}",
                         "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64", "--cap-drop", "ALL",
                         "--security-opt", "no-new-privileges:true", "--read-only", "--user", "65534:65534",
                         "--tmpfs", "/workspace:rw,exec,nosuid,size=32m,uid=65534,gid=65534", "--workdir", "/workspace",
                         "--entrypoint", "sleep", grader_image_digest(), "infinity", timeout=remaining_timeout(deadline))
        if created.returncode:
            raise HTTPException(503, "受限判定器创建失败或同一实例组正在判定")
        grader_created = True
        evidence = collect_evidence(source_name, required_paths, deadline) if needs_files else None
        if evidence is not None and evidence.returncode:
            return {"passed": False, "message": checkpoint.get("failure_message", "检查点证据缺失或不安全"), "evidence": {"exit_code": evidence.returncode, "output": "", "truncated": False, "grader": "evidence_rejected", "judge_type": kind}}
        started = docker("start", grader_name, timeout=remaining_timeout(deadline))
        if started.returncode:
            raise HTTPException(503, "受限判定器启动失败")
        if evidence is not None:
            copied_in = docker_bytes("exec", "-i", "--user", "65534:65534", grader_name, "tar", "-C", "/workspace", "-xf", "-", timeout=remaining_timeout(deadline), input_bytes=evidence.stdout)
            if copied_in.returncode:
                raise HTTPException(503, "判定证据传入失败")
        result = docker("exec", "--user", "65534:65534", grader_name, *command, timeout=remaining_timeout(deadline))
        output = (result.stdout + result.stderr)[:spec.output_limit_bytes]
        passed = result.returncode == (config["expected_exit"] if kind == "COMMAND_EXIT" else 0)
        if kind == "COMMAND_EXIT" and config.get("output_contains"):
            passed = passed and config["output_contains"] in output
        isolation = "ephemeral_non_root_no_network" if needs_files else "ephemeral_non_root_internal_group_network"
        return {"passed": passed, "message": "检查点通过" if passed else checkpoint.get("failure_message", "检查点未通过"), "evidence": {"exit_code": result.returncode, "output": output, "truncated": len(result.stdout + result.stderr) > spec.output_limit_bytes, "grader": isolation, "judge_type": kind}}
    finally:
        cleaned = remove_owned_container(grader_name, evaluation_id)
        if grader_created and not cleaned:
            raise HTTPException(503, "临时判定器清理失败")


@app.websocket("/runtime-groups/{group_id}/terminal/{node_key}")
async def terminal(websocket: WebSocket, group_id: str, node_key: str):
    expected = os.getenv("YUEKE_NODE_AGENT_TOKEN")
    if not expected or websocket.headers.get("authorization") != f"Bearer {expected}" or not SAFE_ID.fullmatch(group_id) or not SAFE_ID.fullmatch(node_key):
        await websocket.close(code=4401)
        return
    name = container_name(group_id, node_key)
    labels = docker("inspect", "--format", "{{index .Config.Labels \"io.yueke.runtime-group\"}}", name)
    if labels.returncode or labels.stdout.strip() != group_id:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    master_fd = None
    if os.name == "posix":
        import fcntl
        import pty
        import struct
        import termios

        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", "-it", "--user", "65534:65534", name, "/bin/sh",
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, start_new_session=True,
        )
        os.close(slave_fd)
    else:
        process = await asyncio.create_subprocess_exec("docker", "exec", "-i", "--user", "65534:65534", name, "/bin/sh", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    def decode_message(message: dict) -> tuple[str, bytes | tuple[int, int]]:
        if message.get("bytes") is not None:
            return "input", message["bytes"]
        text = message.get("text", "")
        try:
            control = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return "input", str(text).encode()
        if isinstance(control, dict) and control.get("type") == "resize":
            rows = max(8, min(int(control.get("rows", 24)), 200))
            cols = max(20, min(int(control.get("cols", 80)), 400))
            return "resize", (rows, cols)
        return "input", str(text).encode()

    async def to_container():
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            kind, value = decode_message(message)
            if kind == "resize":
                if master_fd is not None:
                    rows, cols = value
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                continue
            data = value
            if master_fd is not None:
                await asyncio.to_thread(os.write, master_fd, data)
            else:
                process.stdin.write(data.replace(b"\r", b"\n"))
                await process.stdin.drain()

    async def from_container():
        if master_fd is not None:
            while True:
                try:
                    data = await asyncio.to_thread(os.read, master_fd, 4096)
                except OSError:
                    return
                if not data:
                    return
                await websocket.send_bytes(data)
        else:
            while data := await process.stdout.read(4096):
                await websocket.send_bytes(data)

    try:
        await asyncio.gather(to_container(), from_container())
    except WebSocketDisconnect:
        pass
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()
        if master_fd is not None:
            os.close(master_fd)


@app.post("/runtime-groups/{group_id}/capture/start", dependencies=[Depends(require_control)])
def capture_start(group_id: str):
    raise HTTPException(501, "流量采集器尚未部署")


@app.post("/runtime-groups/{group_id}/capture/stop", dependencies=[Depends(require_control)])
def capture_stop(group_id: str):
    raise HTTPException(501, "流量采集器尚未部署")
