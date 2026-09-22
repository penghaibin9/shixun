"""真实 Linux Docker 流量采集门禁；不挂载 Docker socket。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from node_agent import app as agent


def docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=timeout, check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], action: str) -> str:
    if result.returncode:
        raise RuntimeError(f"{action}失败: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def main() -> None:
    engine = require_ok(docker("info", "--format", "{{.OSType}} {{.ServerVersion}}", timeout=15), "读取 Docker Engine")
    if not engine.startswith("linux "):
        raise RuntimeError("真实抓包门禁只接受 Linux Docker Engine")

    suffix = os.urandom(5).hex()
    group_id = f"capture-gate-{suffix}"
    network = f"yk-capture-gate-net-{suffix}"
    student = f"yk-capture-gate-student-{suffix}"
    target = f"yk-capture-gate-target-{suffix}"
    image_tag = f"yueke-traffic-capture-gate:{suffix}"
    capture_container = agent.capture_container_name(group_id)
    capture_id = None
    image_id = None

    with tempfile.TemporaryDirectory(prefix="yueke-capture-gate-") as capture_dir:
        try:
            image_id = require_ok(
                docker(
                    "build", "--quiet", "--tag", image_tag,
                    str(ROOT / "tests" / "fixtures" / "traffic-capture"),
                    timeout=300,
                ),
                "构建固定抓包镜像",
            ).splitlines()[-1]
            if not image_id.startswith("sha256:"):
                image_id = require_ok(docker("image", "inspect", image_tag, "--format", "{{.Id}}"), "读取抓包镜像摘要")

            require_ok(docker("network", "create", "--internal", network), "创建门禁隔离网络")
            expiry = "2099-01-01T00:00:00+00:00"
            require_ok(
                docker(
                    "run", "-d", "--name", target, "--network", network,
                    "--network-alias", "target", "nginx:1.27-alpine",
                ),
                "启动门禁目标容器",
            )
            require_ok(
                docker(
                    "run", "-d", "--name", student, "--network", network,
                    "--label", f"io.yueke.runtime-group={group_id}",
                    "--label", "io.yueke.role=STUDENT_WORKSTATION",
                    "--label", "io.yueke.node-key=student",
                    "--label", f"io.yueke.provision-id={'a' * 32}",
                    "--label", "io.yueke.startup-profile=generic-shell-v1",
                    "--label", f"io.yueke.expires-at={expiry}",
                    "alpine:3.20", "sleep", "infinity",
                ),
                "启动门禁学生容器",
            )

            os.environ["YUEKE_AGENT_CAPTURE_DIR"] = capture_dir
            os.environ["YUEKE_AGENT_CAPTURE_DIGEST"] = image_id
            os.environ["YUEKE_AGENT_ALLOWED_DIGESTS"] = image_id
            os.environ["YUEKE_NODE_AGENT_TOKEN"] = "capture-gate-control-token"
            headers = {"Authorization": "Bearer capture-gate-control-token"}
            client = TestClient(agent.app)

            started_response = client.post(f"/runtime-groups/{group_id}/capture/start", headers=headers)
            if started_response.status_code != 200:
                raise RuntimeError(f"真实抓包启动接口失败: {started_response.text}")
            started = started_response.json()
            capture_id = started["capture_id"]
            replayed = client.post(f"/runtime-groups/{group_id}/capture/start", headers=headers).json()
            if replayed["capture_id"] != capture_id or not replayed["idempotent_replay"]:
                raise RuntimeError("抓包启动重放不是幂等响应")

            capture_security = json.loads(require_ok(docker("inspect", capture_container), "检查抓包容器"))[0]
            host = capture_security["HostConfig"]
            if host["Privileged"] or host.get("Binds") or any(mount.get("Type") == "bind" for mount in capture_security.get("Mounts", [])):
                raise RuntimeError("抓包容器使用了 privileged 或宿主目录挂载")
            added = {value.removeprefix("CAP_") for value in (host.get("CapAdd") or [])}
            dropped = {value.removeprefix("CAP_") for value in (host.get("CapDrop") or [])}
            if added != {"NET_RAW"} or dropped != {"ALL"}:
                raise RuntimeError("抓包容器能力边界不符合预期")
            if not str(host.get("NetworkMode", "")).startswith("container:"):
                raise RuntimeError("抓包容器未限定到学生容器网络命名空间")

            time.sleep(1)
            require_ok(docker("exec", student, "wget", "-qO-", "http://target/", timeout=20), "生成真实实验网络流量")
            time.sleep(0.5)
            try:
                stopped_response = client.post(f"/runtime-groups/{group_id}/capture/stop", headers=headers)
                if stopped_response.status_code != 200:
                    raise RuntimeError(f"真实抓包停止接口失败: {stopped_response.text}")
                stopped = stopped_response.json()
            except Exception as error:
                diagnostic = docker("inspect", capture_container, "--format", "{{json .State}}")
                logs = docker("logs", capture_container)
                raise RuntimeError(
                    f"真实抓包停止失败: {error}; state={diagnostic.stdout.strip()}; "
                    f"logs={(logs.stdout + logs.stderr).strip()}"
                ) from error
            if stopped["status"] != "COMPLETED" or stopped["size_bytes"] <= 24 or stopped["packet_count"] < 1:
                raise RuntimeError(f"抓包产物摘要无效: {stopped}")
            replayed_stop = client.post(f"/runtime-groups/{group_id}/capture/stop", headers=headers).json()
            if replayed_stop["sha256"] != stopped["sha256"] or not replayed_stop["idempotent_replay"]:
                raise RuntimeError("抓包停止重放不是幂等响应")

            unauthorized = client.get(f"/runtime-groups/{group_id}/capture/artifact")
            if unauthorized.status_code != 401:
                raise RuntimeError("未授权抓包取回未被拒绝")
            downloaded = client.get(
                f"/runtime-groups/{group_id}/capture/artifact",
                headers=headers,
            )
            if downloaded.status_code != 200 or downloaded.headers.get("x-content-sha256") != stopped["sha256"]:
                raise RuntimeError("控制面未能安全取回抓包产物")
            if len(downloaded.content) != stopped["size_bytes"]:
                raise RuntimeError("取回的抓包产物大小与节点摘要不一致")
            if docker("inspect", capture_container).returncode == 0:
                raise RuntimeError("抓包停止后侧车容器未清理")

            print(json.dumps({
                "status": "PASS",
                "engine": engine,
                "runtime_group_id": group_id,
                "capture_id": capture_id,
                "size_bytes": stopped["size_bytes"],
                "packet_count": stopped["packet_count"],
                "sha256": stopped["sha256"],
                "idempotent_start": True,
                "idempotent_stop": True,
                "unauthorized_download_rejected": True,
                "artifact_download_verified": True,
                "capture_container_cleaned": True,
                "docker_socket_mounted": False,
            }, ensure_ascii=False))
        finally:
            docker("rm", "-f", capture_container, student, target, timeout=30)
            docker("network", "rm", network, timeout=30)
            if image_id:
                docker("image", "rm", "-f", image_tag, timeout=30)


if __name__ == "__main__":
    main()
