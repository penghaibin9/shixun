"""最小权限 Node Agent；唯一 Docker Engine 操作边界。"""
import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import PurePosixPath

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="跃科实验节点代理", docs_url=None, redoc_url=None, openapi_url=None)
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")
SAFE_PATH = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def docker(*args: str, timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], input=input_text, text=True, capture_output=True, timeout=timeout, check=False)
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


def container_name(group_id: str, node_key: str) -> str:
    return f"yk-{group_id[:24]}-{node_key[:24]}".lower()


def network_name(group_id: str, key: str) -> str:
    return f"yk-{group_id[:24]}-{key[:24]}".lower()


def group_containers(group_id: str) -> list[dict]:
    result = docker("ps", "-a", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{json .}}")
    if result.returncode:
        raise HTTPException(503, "无法读取容器状态")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


@app.on_event("startup")
def reconcile_expired_groups() -> None:
    """代理重启时只回收带跃科标签且已过期的实例组。"""
    rows = docker("ps", "-a", "--filter", "label=io.yueke.expires-at", "--format", "{{.Label \"io.yueke.runtime-group\"}}|{{.Label \"io.yueke.expires-at\"}}", timeout=15)
    if rows.returncode:
        return
    current = datetime.now(timezone.utc)
    expired: set[str] = set()
    for line in rows.stdout.splitlines():
        group_id, _, value = line.partition("|")
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


@app.post("/runtime-groups", dependencies=[Depends(require_control)], status_code=201)
def create_group(spec: GroupSpec):
    if spec.expires_at.replace(tzinfo=None) <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(422, "实例过期时间无效")
    if group_containers(spec.runtime_group_id):
        return inspect_group(spec.runtime_group_id)
    allowed = allowed_digests()
    requested = {x.image_digest for x in spec.containers}
    if not allowed or not requested.issubset(allowed):
        raise HTTPException(422, "镜像摘要不在节点白名单")
    if any(x.internet_access or x.egress_allowlist for x in spec.networks):
        raise HTTPException(422, "首期节点代理仅接受无外网隔离网络")
    created_networks: list[str] = []
    created_containers: list[str] = []
    try:
        for net in spec.networks:
            name = network_name(spec.runtime_group_id, net.network_key)
            result = docker("network", "create", "--internal", "--label", f"io.yueke.runtime-group={spec.runtime_group_id}", "--label", f"io.yueke.network-key={net.network_key}", name)
            if result.returncode:
                raise HTTPException(503, "创建隔离网络失败")
            created_networks.append(name)
        primary = created_networks[0]
        for item in spec.containers:
            name = container_name(spec.runtime_group_id, item.node_key)
            args = ["run", "-d", "--name", name, "--network", primary,
                    "--label", f"io.yueke.runtime-group={spec.runtime_group_id}", "--label", f"io.yueke.node-key={item.node_key}",
                    "--label", f"io.yueke.expires-at={spec.expires_at.isoformat()}", "--cpus", str(item.cpu_limit),
                    "--memory", f"{item.memory_mb}m", "--pids-limit", str(item.pids_limit), "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges:true", "--read-only", "--user", "65534:65534",
                    "--tmpfs", "/workspace:rw,exec,nosuid,size=64m,uid=65534,gid=65534", "--workdir", "/workspace",
                    item.image_digest, "sleep", "infinity"]
            result = docker(*args, timeout=60)
            if result.returncode:
                raise HTTPException(503, "创建受限实验容器失败")
            created_containers.append(name)
        return inspect_group(spec.runtime_group_id)
    except Exception:
        for name in created_containers:
            docker("rm", "-f", name)
        for name in created_networks:
            docker("network", "rm", name)
        raise


@app.get("/runtime-groups/{group_id}", dependencies=[Depends(require_control)])
def inspect_group(group_id: str):
    if not SAFE_ID.fullmatch(group_id):
        raise HTTPException(422, "实例组标识无效")
    containers = group_containers(group_id)
    networks = docker("network", "ls", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{json .}}")
    network_rows = [json.loads(x) for x in networks.stdout.splitlines() if x.strip()]
    return {
        "provider_group_id": group_id,
        "status": "RUNNING" if containers and all(x.get("State") == "running" for x in containers) else "FAILED",
        "containers": [{"container_id": x["ID"], "name": x["Names"], "node_key": docker("inspect", "--format", "{{index .Config.Labels \"io.yueke.node-key\"}}", x["ID"]).stdout.strip()} for x in containers],
        "networks": [{"network_id": x["ID"], "network_key": docker("network", "inspect", "--format", "{{index .Labels \"io.yueke.network-key\"}}", x["ID"]).stdout.strip(), "isolation_checks": {"business_mysql": "DENY", "other_student": "DENY", "grader": "ALLOW_SAME_GROUP_ONLY"}} for x in network_rows],
    }


@app.post("/runtime-groups/{group_id}/destroy", dependencies=[Depends(require_control)])
def destroy_group(group_id: str):
    if not SAFE_ID.fullmatch(group_id):
        raise HTTPException(422, "实例组标识无效")
    for item in group_containers(group_id):
        docker("rm", "-f", item["ID"])
    networks = docker("network", "ls", "--filter", f"label=io.yueke.runtime-group={group_id}", "--format", "{{.ID}}")
    for network_id in networks.stdout.splitlines():
        if network_id:
            docker("network", "rm", network_id)
    return {"provider_group_id": group_id, "status": "DESTROYED"}


def safe_file(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or not SAFE_PATH.fullmatch(value):
        raise HTTPException(422, "检查点文件名不安全")
    return value


@app.post("/runtime-groups/{group_id}/exec", dependencies=[Depends(require_control)])
def execute_checkpoint(group_id: str, spec: ExecSpec):
    if spec.operation != "judge" or not SAFE_ID.fullmatch(group_id):
        raise HTTPException(422, "仅允许受控检查点判定")
    checkpoint = spec.checkpoint
    source_name = container_name(group_id, "student-rsa")
    source_image = docker("inspect", "--format", "{{.Image}}", source_name)
    if source_image.returncode or not source_image.stdout.strip().startswith("sha256:"):
        raise HTTPException(404, "学生操作容器不存在")
    kind = checkpoint.get("judge_type")
    config = checkpoint.get("judge_config_json", {})
    if kind == "FILE_EXISTS":
        paths = [safe_file(config["path"]), *[safe_file(x) for x in config.get("additional_paths", [])]]
        command = ["/bin/sh", "-c", " && ".join(f"test -s ./{path}" for path in paths)]
        if config.get("format") == "PEM":
            command = ["/bin/sh", "-c", "test -s ./private.pem && test -s ./public.pem && openssl pkey -in ./private.pem -noout && openssl pkey -pubin -in ./public.pem -noout"]
    elif kind == "FILE_HASH":
        left, right = safe_file(config["left_path"]), safe_file(config["right_path"])
        command = ["/bin/sh", "-c", f"test \"$(sha256sum ./{left} | cut -d' ' -f1)\" = \"$(sha256sum ./{right} | cut -d' ' -f1)\""]
    elif kind == "COMMAND_EXIT" and config.get("command_ref") == "verify_signature":
        command = ["openssl", "dgst", "-sha256", "-verify", "public.pem", "-signature", "signature.bin", "source.txt"]
    else:
        raise HTTPException(422, "检查点类型未获节点代理批准")
    grader_name = f"yk-grader-{group_id[:18]}-{str(checkpoint.get('checkpoint_id', 'cp'))[:16]}".lower()
    evidence = docker_bytes("exec", "--user", "65534:65534", source_name, "tar", "-C", "/workspace", "-cf", "-", ".", timeout=spec.timeout_seconds)
    if evidence.returncode:
        raise HTTPException(503, "无法准备判定证据")
    created = docker("run", "-d", "--name", grader_name, "--network", "none", "--label", f"io.yueke.runtime-group={group_id}",
                     "--label", "io.yueke.role=grader", "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
                     "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--read-only", "--user", "65534:65534",
                     "--tmpfs", "/workspace:rw,exec,nosuid,size=32m,uid=65534,gid=65534", "--workdir", "/workspace",
                     source_image.stdout.strip(), "sleep", "infinity", timeout=spec.timeout_seconds)
    if created.returncode:
        raise HTTPException(503, "受限判定器启动失败")
    try:
        copied_in = docker_bytes("exec", "-i", "--user", "65534:65534", grader_name, "tar", "-C", "/workspace", "-xf", "-", timeout=spec.timeout_seconds, input_bytes=evidence.stdout)
        if copied_in.returncode:
            raise HTTPException(503, "判定证据传入失败")
        result = docker("exec", "--user", "65534:65534", grader_name, *command, timeout=spec.timeout_seconds)
        output = (result.stdout + result.stderr)[:spec.output_limit_bytes]
        passed = result.returncode == 0
        if kind == "COMMAND_EXIT" and config.get("output_contains"):
            passed = passed and config["output_contains"] in output
        return {"passed": passed, "message": "检查点通过" if passed else checkpoint.get("failure_message", "检查点未通过"), "evidence": {"exit_code": result.returncode, "output": output, "truncated": len(result.stdout + result.stderr) > spec.output_limit_bytes, "grader": "ephemeral_non_root_no_network"}}
    finally:
        docker("rm", "-f", grader_name)


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
