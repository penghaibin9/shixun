"""真实 Linux Docker 门禁。需由 scripts/run-runtime-gate.ps1 在隔离开发环境运行。"""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from pathlib import Path
from zipfile import ZipFile

import httpx
import websockets

BASE = os.getenv("YUEKE_GATE_API_URL", "http://127.0.0.1:18080")
AGENT_URL = os.getenv("YUEKE_GATE_NODE_AGENT_URL", "http://127.0.0.1:19443").rstrip("/")
EXPECT_POSIX_PTY = os.getenv("YUEKE_GATE_EXPECT_POSIX_PTY") == "1"
DIGEST = os.environ["YUEKE_GATE_IMAGE_DIGEST"]
PCAP_MAGICS = {b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"}
RUN = uuid4().hex[:8]
TEACHER = {"X-User-Id": "teacher_d_gate", "X-Role": "teacher", "X-Teacher-Id": "teacher_d_gate", "X-Permissions": "labs.read,labs.write,labs.publish,labs.knowledge.write,runtime.read,runtime.preview,infrastructure.read,infrastructure.write", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}


def student_headers(number: int) -> dict[str, str]:
    return {"X-User-Id": f"user_d_{RUN}_{number}", "X-Role": "student", "X-Student-Id": f"student_d_{RUN}_{number}", "X-Permissions": "runtime.read,runtime.start,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}


def runtime_container_name(group_id: str, node_key: str) -> str:
    group_token = f"{group_id[:16]}-{sha256(group_id.encode()).hexdigest()[:10]}"
    node_token = f"{node_key[:12]}-{sha256(node_key.encode()).hexdigest()[:8]}"
    return f"yk-{group_token}-{node_token}".lower()


def checked(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:500]}")
    return response.json()


def terminal_url(instance_id: str) -> str:
    return BASE.replace("http://", "ws://").replace("https://", "wss://") + f"/api/v1/runtime-instances/{instance_id}/terminal"


async def issue_terminal_token(instance_id: str, headers: dict[str, str], idle_timeout_seconds: int = 300) -> dict:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        return checked(await client.post(
            f"/api/v1/runtime-instances/{instance_id}/terminal-token",
            headers=headers,
            json={"idle_timeout_seconds": idle_timeout_seconds},
        ))


async def read_until(socket, marker: str) -> str:
    output = b""
    while marker.encode() not in output:
        frame = await asyncio.wait_for(socket.recv(), timeout=30)
        output += frame if isinstance(frame, bytes) else frame.encode()
    return output.decode(errors="replace")


async def command_with_token(instance_id: str, token: str, commands: str, marker: str) -> str:
    async with websockets.connect(terminal_url(instance_id), open_timeout=10) as socket:
        await socket.send(json.dumps({"token": token}))
        ready = json.loads(await socket.recv())
        if ready.get("type") != "ready":
            raise RuntimeError("终端未就绪")
        await socket.send(commands + "\n")
        return await read_until(socket, marker)


async def expect_terminal_rejected(instance_id: str, token: str, label: str, expected_code: int = 4403) -> None:
    try:
        async with websockets.connect(terminal_url(instance_id), open_timeout=10) as rejected:
            await rejected.send(json.dumps({"token": token}))
            await rejected.recv()
    except websockets.ConnectionClosed as exc:
        if exc.code != expected_code:
            raise RuntimeError(f"{label}返回了异常关闭码: {exc.code}") from exc
    else:
        raise RuntimeError(f"{label}未被拒绝")


async def shell(instance_id: str, headers: dict[str, str], commands: str, marker: str) -> str:
    token = (await issue_terminal_token(instance_id, headers))["token"]
    output = await command_with_token(instance_id, token, commands, marker)
    await expect_terminal_rejected(instance_id, token, "终端令牌重复使用")
    return output


async def verify_terminal_resize(instance_id: str, headers: dict[str, str]) -> dict:
    token = (await issue_terminal_token(instance_id, headers))["token"]
    async with websockets.connect(terminal_url(instance_id), open_timeout=10) as socket:
        await socket.send(json.dumps({"token": token}))
        ready = json.loads(await socket.recv())
        if ready.get("type") != "ready":
            raise RuntimeError("终端尺寸门禁未就绪")
        await socket.send("stty size 2>/dev/null || echo NO_POSIX_PTY\necho STTY_INITIAL_DONE\n")
        initial = await read_until(socket, "STTY_INITIAL_DONE")
        initial_size = re.search(r"(?:^|[\r\n])\s*(\d+)\s+(\d+)\s*(?:[\r\n]|$)", initial)
        if not initial_size:
            if EXPECT_POSIX_PTY:
                raise RuntimeError(f"声明为 POSIX/PTTY 的节点未提供可查询终端尺寸: {initial}")
            return {"status": "SKIPPED_WINDOWS_FALLBACK", "reason": "节点代理未提供 POSIX/PTTY，resize 未计为通过"}
        before = [int(initial_size.group(1)), int(initial_size.group(2))]
        if before != [24, 80]:
            raise RuntimeError(f"终端初始尺寸不是 24x80: {before}")
        await socket.send(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
        await asyncio.sleep(0.2)
        await socket.send("stty size 2>/dev/null || echo RESIZE_FAILED\necho STTY_RESIZED_DONE\n")
        resized = await read_until(socket, "STTY_RESIZED_DONE")
        resized_size = re.search(r"(?:^|[\r\n])\s*(\d+)\s+(\d+)\s*(?:[\r\n]|$)", resized)
        after = [int(resized_size.group(1)), int(resized_size.group(2))] if resized_size else None
        if after != [30, 100]:
            raise RuntimeError(f"终端 resize 后尺寸不是 30x100: {after}; output={resized}")
    await expect_terminal_rejected(instance_id, token, "尺寸门禁令牌重复使用")
    return {"status": "PASS", "before": before, "after": after}


def seconds_until_expiry(expires_at: str) -> float:
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return max((expiry - datetime.now(timezone.utc)).total_seconds() + 0.5, 0)


async def verify_traffic_artifacts(
    client: httpx.AsyncClient,
    instance_id: str,
    headers: dict[str, str],
    expected_minimum: int,
) -> list[dict]:
    listed = checked(await client.get(f"/api/v1/runtime-instances/{instance_id}/traffic-artifacts", headers=headers))
    artifacts = listed["items"]
    if len(artifacts) < expected_minimum:
        raise RuntimeError(f"真实流量制品数量不足: expected>={expected_minimum}, actual={len(artifacts)}")
    verified = []
    for artifact in artifacts:
        if (
            artifact.get("type") != "TRAFFIC"
            or not re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256", ""))
            or artifact.get("size_bytes", 0) <= 24
        ):
            raise RuntimeError(f"流量制品登记无效: {artifact}")
        issued = checked(await client.post(
            f"/api/v1/runtime/log-artifacts/{artifact['artifact_id']}/download-url",
            headers=headers,
        ))
        downloaded = await client.get(issued["download_url"], headers=headers)
        if downloaded.status_code != 200 or downloaded.headers.get("content-type", "").split(";", 1)[0] != "application/zip":
            raise RuntimeError(f"流量制品下载失败: {downloaded.status_code} {downloaded.text[:200]}")
        with ZipFile(BytesIO(downloaded.content)) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise RuntimeError(f"单项流量制品下载包内容异常: {names}")
            content = archive.read(names[0])
        if (
            len(content) != artifact["size_bytes"]
            or sha256(content).hexdigest() != artifact["sha256"]
            or content[:4] not in PCAP_MAGICS
        ):
            raise RuntimeError(f"下载的 PCAP 摘要、大小或格式与登记不一致: {artifact['artifact_id']}")
        verified.append({
            "artifact_id": artifact["artifact_id"],
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
        })
    return verified


async def run_gate(starts: list[tuple[dict, dict, dict[str, str]]]) -> None:
    spec = json.loads((Path(__file__).parents[1] / "backend/app/labs/fixtures/rsa-v1.json").read_text(encoding="utf-8"))
    spec["lab_definition_id"] = "lab_rsa_d_gate_v3"
    spec["name"] = "RSA 真实运行门禁实验"
    for node in spec["nodes"]:
        node["image_id"], node["image_digest"] = "img_python_openssl_gate", DIGEST
    for binding in spec["image_bindings"]:
        binding["infra_image_id"], binding["digest"] = "img_python_openssl_gate", DIGEST
    for checkpoint in spec["checkpoints"]:
        checkpoint["checkpoint_id"] = f"{checkpoint['checkpoint_id']}_gate_v3"
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        labs = checked(await client.get("/api/v1/labs", headers=TEACHER))["items"]
        lab = next((x for x in labs if x["lab_definition_id"] == spec["lab_definition_id"]), None)
        if not lab:
            lab = checked(await client.post("/api/v1/labs", headers={**TEACHER, "X-Idempotency-Key": "d-gate-lab-create-v3"}, json={"course_id": "course_data_security", "code": "EXP-RSA-D-GATE-V3", "category": "密码学", "objective": "验证真实容器、终端、隔离和五类判定闭环。", "spec": spec}))
            version_id = lab["latest_version"]["lab_version_id"]
            checked(await client.post(f"/api/v1/lab-versions/{version_id}/validate", headers={**TEACHER, "X-Idempotency-Key": "d-gate-lab-validate-v3"}))
            checked(await client.post(f"/api/v1/lab-versions/{version_id}/publish", headers={**TEACHER, "X-Idempotency-Key": "d-gate-lab-publish-v3"}))
        version_id = lab["latest_version"]["lab_version_id"]
        await client.post("/api/v1/infrastructure/images", headers=TEACHER, json={"image_id": "img_python_openssl_gate", "name": "Python OpenSSL 门禁镜像", "tag": "3.11-bookworm", "digest": DIGEST, "size_bytes": 0, "scan_status": "PASSED", "startup_check_status": "PASSED", "teaching_validation_status": "PASSED", "enabled": True})
        checked(await client.post("/api/v1/infrastructure/nodes", headers=TEACHER, json={"node_id": "node_docker_desktop_gate", "name": "Docker Desktop Linux 门禁节点", "agent_url": AGENT_URL, "weight": 1000, "labels": {"environment": "gate"}}))

        for number in (1, 2):
            headers = student_headers(number)
            student_id = f"student_d_{RUN}_{number}"
            response = checked(await client.post("/api/v1/runtime/start", headers={**headers, "Idempotency-Key": f"d-real-gate-{RUN}-{number}"}, json={"lab_release_id": "release_d_gate", "lab_version_id": version_id, "course_id": "course_data_security", "class_id": "class_netsec_2301", "student_id": student_id, "mode": "STUDENT"}))
            repeated = checked(await client.post("/api/v1/runtime/start", headers={**headers, "Idempotency-Key": f"d-real-gate-{RUN}-{number}"}, json={"lab_release_id": "release_d_gate", "lab_version_id": version_id, "course_id": "course_data_security", "class_id": "class_netsec_2301", "student_id": student_id, "mode": "STUDENT"}))
            if repeated["runtime_request_id"] != response["runtime_request_id"]:
                raise RuntimeError("幂等启动失败")
            details = [checked(await client.get(f"/api/v1/runtime-instances/{instance_id}", headers=headers)) for instance_id in response["instance_ids"]]
            student_instance = next(x for x in details if x["role"] == "STUDENT_WORKSTATION")
            starts.append((response, student_instance, headers))

    first_response, first_instance, first_headers = starts[0]
    second_instance = starts[1][1]
    second_group = starts[1][0]["runtime_group_id"]
    second_student_name = runtime_container_name(second_group, "student-rsa")
    first_target_name = runtime_container_name(first_response["runtime_group_id"], "target-rsa")
    expired_grant = await issue_terminal_token(first_instance["runtime_instance_id"], first_headers, 30)
    scoped_grant = await issue_terminal_token(first_instance["runtime_instance_id"], first_headers)
    await expect_terminal_rejected(second_instance["runtime_instance_id"], scoped_grant["token"], "终端令牌跨实例使用")
    scoped_output = await command_with_token(
        first_instance["runtime_instance_id"], scoped_grant["token"], "echo INSTANCE_SCOPE_OK", "INSTANCE_SCOPE_OK"
    )
    if "INSTANCE_SCOPE_OK" not in scoped_output:
        raise RuntimeError("终端令牌正确实例连接失败")
    await expect_terminal_rejected(first_instance["runtime_instance_id"], scoped_grant["token"], "终端令牌正确使用后的重放")
    commands = """set -e
printf 'Yueke RSA runtime gate evidence' > source.txt
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out private.pem >/dev/null 2>&1
openssl pkey -in private.pem -pubout -out public.pem
openssl pkeyutl -encrypt -pubin -inkey public.pem -in source.txt -out cipher.bin
openssl pkeyutl -decrypt -inkey private.pem -in cipher.bin -out plain.out
openssl dgst -sha256 -sign private.pem -out signature.bin source.txt
sha256sum source.txt plain.out
cp source.txt report.pdf
python3 -m http.server 18080 --bind 0.0.0.0 >http.log 2>&1 &
echo RSA_DONE"""
    terminal_output = await shell(first_instance["runtime_instance_id"], first_headers, commands, "RSA_DONE")
    if "RSA_DONE" not in terminal_output:
        raise RuntimeError("RSA 终端命令未完成")
    isolation_commands = f"""python -c \"import socket; socket.create_connection(('host.docker.internal',13384),2)\" >/dev/null 2>&1 && echo BUSINESS_FAIL || echo BUSINESS_DENY
getent hosts {second_student_name} >/dev/null && echo OTHER_FAIL || echo OTHER_DENY
getent hosts {first_target_name} >/dev/null && echo GRADER_ALLOW || echo GRADER_FAIL
echo NETWORK_DONE"""
    network_output = await shell(first_instance["runtime_instance_id"], first_headers, isolation_commands, "NETWORK_DONE")
    required = {"BUSINESS_DENY", "OTHER_DENY", "GRADER_ALLOW"}
    if not required.issubset(set(network_output.split())):
        raise RuntimeError(f"网络隔离失败: {network_output}")
    agent_headers = {"Authorization": f"Bearer {os.environ['YUEKE_NODE_AGENT_TOKEN']}"}
    network_judges = [
        {"checkpoint_id": "cp_port_live", "judge_target": "student-rsa:18080", "judge_type": "PORT_LISTEN", "judge_config_json": {"host": "student-rsa", "port": 18080}, "failure_message": "服务端口未监听"},
        {"checkpoint_id": "cp_http_live", "judge_target": "student-rsa:/", "judge_type": "HTTP_RESPONSE", "judge_config_json": {"path": "/", "port": 18080, "status_code": 200}, "failure_message": "网页响应不符合要求"},
    ]
    async with httpx.AsyncClient(base_url=AGENT_URL, timeout=30) as agent_client:
        for checkpoint in network_judges:
            result = checked(await agent_client.post(
                f"/runtime-groups/{first_response['runtime_group_id']}/exec",
                headers=agent_headers,
                json={"operation": "judge", "checkpoint": checkpoint, "timeout_seconds": 10, "output_limit_bytes": 8192},
            ))
            if not result["passed"] or result["evidence"].get("judge_type") != checkpoint["judge_type"]:
                raise RuntimeError(f"{checkpoint['judge_type']} 真实判定失败: {result}")
        await shell(first_instance["runtime_instance_id"], first_headers, "ln -s /etc evidence-link\necho SYMLINK_READY", "SYMLINK_READY")
        symlink_result = checked(await agent_client.post(
            f"/runtime-groups/{first_response['runtime_group_id']}/exec",
            headers=agent_headers,
            json={
                "operation": "judge",
                "checkpoint": {
                    "checkpoint_id": "cp_symlink_reject",
                    "judge_target": "student-rsa:evidence-link/passwd",
                    "judge_type": "FILE_EXISTS",
                    "judge_config_json": {"path": "evidence-link/passwd", "minimum_size": 1},
                    "failure_message": "符号链接证据必须拒绝",
                },
                "timeout_seconds": 10,
                "output_limit_bytes": 8192,
            },
        ))
        if symlink_result["passed"] or symlink_result["evidence"].get("grader") != "evidence_rejected":
            raise RuntimeError(f"符号链接证据未被拒绝: {symlink_result}")
    resize_evidence = await verify_terminal_resize(first_instance["runtime_instance_id"], first_headers)
    await asyncio.sleep(seconds_until_expiry(expired_grant["expires_at"]))
    await expect_terminal_rejected(first_instance["runtime_instance_id"], expired_grant["token"], "过期终端令牌")
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        judged = checked(await client.post(f"/api/v1/runtime-instances/{first_instance['runtime_instance_id']}/rejudge", headers=first_headers))
        if judged["score"] != 100 or len(judged["checkpoint_results"]) != 5:
            raise RuntimeError("RSA 真实判定未达到 100 分")
        rebuilt = checked(await client.post(f"/api/v1/runtime-instances/{first_instance['runtime_instance_id']}/rebuild", headers=first_headers, json={"reason": "门禁恢复演练"}))
        if rebuilt["score"] != 100 or rebuilt["status"] != "RUNNING":
            raise RuntimeError("重建未保留检查点成绩")
        traffic_artifacts = []
        for index, (_, instance, headers) in enumerate(starts):
            # 单次 UDP（用户数据报协议）发送在 Docker Desktop 的短生命周期容器中可能
            # 尚未被侧车读取就进入销毁流程。重复发送并等待抓包进程落盘，同时把实际
            # 解析出的目标地址写回终端输出，避免把仅有 echo 的就绪标记误判为真实流量。
            traffic_command = """python3 -c "import socket,time; address=socket.gethostbyname('target-rsa'); sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); [(sock.sendto(b'capture-gate',(address,9)),time.sleep(0.15)) for _ in range(5)]; sock.close(); print('CAPTURE_TRAFFIC_SENT:'+address)"
sleep 1
echo CAPTURE_TRAFFIC_READY"""
            traffic_output = await shell(
                instance["runtime_instance_id"], headers,
                traffic_command,
                "CAPTURE_TRAFFIC_READY",
            )
            if not re.search(r"CAPTURE_TRAFFIC_SENT:(?:\d{1,3}\.){3}\d{1,3}", traffic_output):
                raise RuntimeError(f"未能生成销毁前真实实验网络流量: {traffic_output[-500:]}")
            checked(await client.post(f"/api/v1/runtime-instances/{instance['runtime_instance_id']}/destroy", headers=headers, json={"reason": "门禁完成回收"}))
            second = checked(await client.post(f"/api/v1/runtime-instances/{instance['runtime_instance_id']}/destroy", headers=headers, json={"reason": "幂等重复回收"}))
            if second["status"] != "DESTROYED":
                raise RuntimeError("幂等销毁失败")
            traffic_artifacts.extend(await verify_traffic_artifacts(
                client, instance["runtime_instance_id"], headers, 2 if index == 0 else 1,
            ))
    g5 = "PASS" if resize_evidence["status"] == "PASS" else "PARTIAL"
    print(json.dumps({"G4": "PASS", "G5": g5, "G6": "PASS", "rsa_score": 100, "checkpoint_count": 5, "judge_types_executed": ["FILE_EXISTS", "FILE_HASH", "COMMAND_EXIT", "PORT_LISTEN", "HTTP_RESPONSE"], "symlink_evidence_rejected": True, "network": sorted(required), "terminal_websocket": "PASS", "terminal_resize": resize_evidence, "single_use_terminal_token": True, "wrong_instance_token_rejected": True, "expired_token_rejected": True, "idempotent_start": True, "idempotent_destroy": True, "rebuild_preserved_score": True, "traffic_capture": {"status": "PASS", "artifacts": traffic_artifacts, "download_sha256_verified": True}}, ensure_ascii=False))


async def cleanup_started(starts: list[tuple[dict, dict, dict[str, str]]]) -> None:
    if not starts:
        return
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        for _, instance, headers in starts:
            try:
                await client.post(
                    f"/api/v1/runtime-instances/{instance['runtime_instance_id']}/destroy",
                    headers=headers,
                    json={"reason": "门禁异常退出回收"},
                )
            except httpx.HTTPError:
                pass


async def main() -> None:
    starts: list[tuple[dict, dict, dict[str, str]]] = []
    try:
        await run_gate(starts)
    except BaseException:
        await cleanup_started(starts)
        raise


if __name__ == "__main__":
    asyncio.run(main())
