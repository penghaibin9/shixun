"""真实 Linux Docker 门禁。需由 scripts/run-runtime-gate.ps1 在隔离开发环境运行。"""
import asyncio
import json
import os
from uuid import uuid4
from pathlib import Path

import httpx
import websockets

BASE = os.getenv("YUEKE_GATE_API_URL", "http://127.0.0.1:18080")
DIGEST = os.environ["YUEKE_GATE_IMAGE_DIGEST"]
RUN = uuid4().hex[:8]
TEACHER = {"X-User-Id": "teacher_d_gate", "X-Role": "teacher", "X-Teacher-Id": "teacher_d_gate", "X-Permissions": "labs.read,labs.write,labs.publish,labs.knowledge.write,runtime.read,runtime.preview,infrastructure.read,infrastructure.write", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}


def student_headers(number: int) -> dict[str, str]:
    return {"X-User-Id": f"user_d_{RUN}_{number}", "X-Role": "student", "X-Student-Id": f"student_d_{RUN}_{number}", "X-Permissions": "runtime.read,runtime.start,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}


def checked(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:500]}")
    return response.json()


async def shell(instance_id: str, headers: dict[str, str], commands: str, marker: str) -> str:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        token = checked(await client.post(f"/api/v1/runtime-instances/{instance_id}/terminal-token", headers=headers, json={"idle_timeout_seconds": 300}))["token"]
    ws_url = BASE.replace("http://", "ws://").replace("https://", "wss://") + f"/api/v1/runtime-instances/{instance_id}/terminal"
    output = b""
    async with websockets.connect(ws_url, open_timeout=10) as socket:
        await socket.send(json.dumps({"token": token}))
        ready = json.loads(await socket.recv())
        if ready.get("type") != "ready":
            raise RuntimeError("终端未就绪")
        await socket.send(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
        await socket.send(commands + "\n")
        while marker.encode() not in output:
            frame = await asyncio.wait_for(socket.recv(), timeout=30)
            output += frame if isinstance(frame, bytes) else frame.encode()
    try:
        async with websockets.connect(ws_url, open_timeout=10) as replay:
            await replay.send(json.dumps({"token": token}))
            await replay.recv()
    except websockets.ConnectionClosed as exc:
        if exc.code != 4403:
            raise RuntimeError(f"终端令牌重复使用返回了异常关闭码: {exc.code}") from exc
    else:
        raise RuntimeError("终端令牌可被重复使用")
    return output.decode(errors="replace")


async def main() -> None:
    spec = json.loads((Path(__file__).parents[1] / "backend/app/labs/fixtures/rsa-v1.json").read_text(encoding="utf-8"))
    spec["lab_definition_id"] = "lab_rsa_d_gate"
    spec["name"] = "RSA 真实运行门禁实验"
    for node in spec["nodes"]:
        node["image_id"], node["image_digest"] = "img_python_openssl_gate", DIGEST
    for binding in spec["image_bindings"]:
        binding["infra_image_id"], binding["digest"] = "img_python_openssl_gate", DIGEST
    for checkpoint in spec["checkpoints"]:
        checkpoint["checkpoint_id"] = f"{checkpoint['checkpoint_id']}_gate"
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        labs = checked(await client.get("/api/v1/labs", headers=TEACHER))["items"]
        lab = next((x for x in labs if x["lab_definition_id"] == spec["lab_definition_id"]), None)
        if not lab:
            lab = checked(await client.post("/api/v1/labs", headers={**TEACHER, "X-Idempotency-Key": "d-gate-lab-create-v1"}, json={"course_id": "course_data_security", "code": "EXP-RSA-D-GATE", "category": "密码学", "objective": "验证真实容器、终端、隔离和 RSA 判定闭环。", "spec": spec}))
            version_id = lab["latest_version"]["lab_version_id"]
            checked(await client.post(f"/api/v1/lab-versions/{version_id}/validate", headers={**TEACHER, "X-Idempotency-Key": "d-gate-lab-validate-v1"}))
            checked(await client.post(f"/api/v1/lab-versions/{version_id}/publish", headers={**TEACHER, "X-Idempotency-Key": "d-gate-lab-publish-v1"}))
        version_id = lab["latest_version"]["lab_version_id"]
        await client.post("/api/v1/infrastructure/images", headers=TEACHER, json={"image_id": "img_python_openssl_gate", "name": "Python OpenSSL 门禁镜像", "tag": "3.11-bookworm", "digest": DIGEST, "size_bytes": 0, "scan_status": "PASSED", "startup_check_status": "PASSED", "teaching_validation_status": "PASSED", "enabled": True})
        checked(await client.post("/api/v1/infrastructure/nodes", headers=TEACHER, json={"node_id": "node_docker_desktop_gate", "name": "Docker Desktop Linux 门禁节点", "agent_url": "http://127.0.0.1:19443", "weight": 1000, "labels": {"environment": "gate"}}))

        starts = []
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
    second_group = starts[1][0]["runtime_group_id"]
    second_student_name = f"yk-{second_group[:24]}-student-rsa"
    first_target_name = f"yk-{first_response['runtime_group_id'][:24]}-target-rsa"
    commands = """set -e
printf 'Yueke RSA runtime gate evidence' > source.txt
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out private.pem >/dev/null 2>&1
openssl pkey -in private.pem -pubout -out public.pem
openssl pkeyutl -encrypt -pubin -inkey public.pem -in source.txt -out cipher.bin
openssl pkeyutl -decrypt -inkey private.pem -in cipher.bin -out plain.out
openssl dgst -sha256 -sign private.pem -out signature.bin source.txt
sha256sum source.txt plain.out
cp source.txt report.pdf
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
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        judged = checked(await client.post(f"/api/v1/runtime-instances/{first_instance['runtime_instance_id']}/rejudge", headers=first_headers))
        if judged["score"] != 100 or len(judged["checkpoint_results"]) != 5:
            raise RuntimeError("RSA 真实判定未达到 100 分")
        rebuilt = checked(await client.post(f"/api/v1/runtime-instances/{first_instance['runtime_instance_id']}/rebuild", headers=first_headers, json={"reason": "门禁恢复演练"}))
        if rebuilt["score"] != 100 or rebuilt["status"] != "RUNNING":
            raise RuntimeError("重建未保留检查点成绩")
        for _, instance, headers in starts:
            checked(await client.post(f"/api/v1/runtime-instances/{instance['runtime_instance_id']}/destroy", headers=headers, json={"reason": "门禁完成回收"}))
            second = checked(await client.post(f"/api/v1/runtime-instances/{instance['runtime_instance_id']}/destroy", headers=headers, json={"reason": "幂等重复回收"}))
            if second["status"] != "DESTROYED":
                raise RuntimeError("幂等销毁失败")
    print(json.dumps({"G4": "PASS", "G5": "PASS", "G6": "PASS", "rsa_score": 100, "checkpoint_count": 5, "network": sorted(required), "terminal_resize": True, "single_use_terminal_token": True, "idempotent_start": True, "idempotent_destroy": True, "rebuild_preserved_score": True}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
