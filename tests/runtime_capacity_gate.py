"""按 5 → 10 → 20 请求验证单节点容量，不把排队冒充运行成功。"""
import asyncio
import json
import os
import time
from uuid import uuid4

import httpx

BASE = os.getenv("YUEKE_GATE_API_URL", "http://127.0.0.1:18080")
DIGEST = os.environ["YUEKE_GATE_IMAGE_DIGEST"]
RUN = uuid4().hex[:8]
TEACHER = {"X-User-Id": "teacher_d_capacity", "X-Role": "teacher", "X-Teacher-Id": "teacher_d_capacity", "X-Permissions": "labs.read,infrastructure.read,infrastructure.write", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}


def checked(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:300]}")
    return response.json()


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        labs = checked(await client.get("/api/v1/labs", headers=TEACHER))["items"]
        lab = next((x for x in labs if x["lab_definition_id"] == "lab_rsa_d_gate_v3"), None)
        if not lab:
            raise RuntimeError("请先在同一门禁库运行 tests/runtime_gate.py 创建规范 RSA 容量基线")
        version_id = lab["latest_version"]["lab_version_id"]
        await client.post("/api/v1/infrastructure/images", headers=TEACHER, json={"image_id": "img_python_openssl_gate", "name": "Python OpenSSL 门禁镜像", "tag": "3.11-bookworm", "digest": DIGEST, "size_bytes": 0, "scan_status": "PASSED", "startup_check_status": "PASSED", "teaching_validation_status": "PASSED", "enabled": True})
        checked(await client.post("/api/v1/infrastructure/nodes", headers=TEACHER, json={"node_id": "node_docker_desktop_gate", "name": "Docker Desktop Linux 门禁节点", "agent_url": "http://127.0.0.1:19443", "weight": 1000, "labels": {"environment": "gate"}}))
        results = []
        stages = []
        started_at = time.perf_counter()
        for number in range(1, 21):
            student_id = f"student_cap_{RUN}_{number}"
            headers = {"X-User-Id": f"user_cap_{RUN}_{number}", "X-Role": "student", "X-Student-Id": student_id, "X-Permissions": "runtime.read,runtime.start,runtime.destroy", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}
            before = time.perf_counter()
            response = await client.post("/api/v1/runtime/start", headers={**headers, "Idempotency-Key": f"capacity-{RUN}-{number}"}, json={"lab_release_id": f"release_capacity_{RUN}", "lab_version_id": version_id, "course_id": "course_data_security", "class_id": "class_netsec_2301", "student_id": student_id, "mode": "STUDENT"})
            body = checked(response)
            results.append({"number": number, "status": body["status"], "http_status": response.status_code, "seconds": round(time.perf_counter() - before, 3), "request": body, "headers": headers})
            if number in {5, 10, 20}:
                node = next(x for x in checked(await client.get("/api/v1/infrastructure/nodes", headers=TEACHER))["items"] if x["node_id"] == "node_docker_desktop_gate")
                stages.append({"requested": number, "running": sum(x["status"] == "RUNNING" for x in results), "queued": sum(x["status"] == "QUEUED" for x in results), "failed": sum(x["status"] == "FAILED" for x in results), "elapsed_seconds": round(time.perf_counter() - started_at, 3), "cpu_available": node["capacity"]["cpu_available"], "memory_available_mb": node["capacity"]["memory_available_mb"]})
        for item in results:
            body, headers = item["request"], item["headers"]
            if body["status"] == "RUNNING":
                checked(await client.post(f"/api/v1/runtime-instances/{body['instance_ids'][0]}/destroy", headers=headers, json={"reason": "容量门禁完成回收"}))
            elif body["status"] == "QUEUED":
                checked(await client.post(f"/api/v1/runtime/requests/{body['runtime_request_id']}/cancel", headers=headers, json={"reason": "容量门禁完成取消排队"}))
        print(json.dumps({"stages": stages, "single_node_measured_running_capacity": max(x["running"] for x in stages), "total_requests": 20, "cleanup": "PASS"}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
