import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox
from app.labs.database import get_session
from app.main import app
from app.runtime import models

pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要真实 MySQL 8.4 的 YUEKE_DATABASE_URL")

STUDENT = {"X-User-Id": "user_student_2301001", "X-Role": "student", "X-Student-Id": "student_2301001", "X-Permissions": "runtime.read,runtime.start,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}
TEACHER = {"X-User-Id": "user_teacher_runtime", "X-Role": "teacher", "X-Teacher-Id": "teacher_runtime", "X-Permissions": "runtime.read,runtime.preview,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal,infrastructure.read,infrastructure.write", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}
DIGEST = "sha256:" + "a" * 64
CLEAN_MODELS = [models.CheckpointResult, models.RuntimeArtifact, models.RuntimeTerminalSession, models.RuntimeResourceUsage, models.RuntimeEvent, models.RuntimeNetwork, models.RuntimeContainer, models.RuntimeInstance, models.RuntimeInstanceGroup, models.RuntimeQueue, models.RuntimeRequest, models.RuntimeReleaseReadModel, models.InfraImageValidation, models.InfraImage, models.InfraNodeHeartbeat, models.InfraNode]
D_EVENT_TYPES = ["lab.instance.started", "lab.instance.failed", "lab.instance.destroyed", "lab.checkpoint.passed", "lab.checkpoint.failed", "lab.submitted"]


def rsa_spec() -> dict:
    data = json.loads((Path(__file__).parents[1] / "app/labs/fixtures/rsa-v1.json").read_text(encoding="utf-8"))
    for node in data["nodes"]:
        node["image_digest"] = DIGEST
    for binding in data["image_bindings"]:
        binding["digest"] = DIGEST
    return data


class FakeCatalog:
    async def frozen_version(self, version_id: str, course_id: str | None = None) -> dict:
        assert version_id == "labv_rsa_v1"
        assert course_id == "course_data_security"
        return rsa_spec()


class FakeAgent:
    def __init__(self):
        self.destroyed = False
        self.cpu_available = 8
        self.memory_available_mb = 8192

    async def health(self):
        return {"status": "ok"}

    async def capacity(self):
        return {"engine": "linux test", "cpu_total": 8, "memory_total_mb": 8192, "cpu_available": self.cpu_available, "memory_available_mb": self.memory_available_mb, "running_groups": 0, "image_digests": [DIGEST]}

    async def create_group(self, payload):
        return {"provider_group_id": payload["runtime_group_id"], "status": "RUNNING", "containers": [{"container_id": f"container-{x['node_key']}", "name": x["node_key"], "node_key": x["node_key"]} for x in payload["containers"]], "networks": [{"network_id": "network-rsa", "network_key": "lab-net-rsa", "isolation_checks": {"business_mysql": "DENY", "other_student": "DENY", "grader": "ALLOW_SAME_GROUP_ONLY"}}]}

    async def destroy(self, provider_group_id):
        self.destroyed = True
        return {"status": "DESTROYED"}

    async def exec(self, provider_group_id, payload):
        return {"passed": True, "message": "检查点通过", "evidence": {"exit_code": 0, "provider_group_id": provider_group_id}}


@pytest.fixture()
def db_and_client():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as session:
        for table in CLEAN_MODELS:
            session.execute(delete(table))
        session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.event_type.like("runtime.%") | DomainEventOutbox.event_type.like("checkpoint.%") | DomainEventOutbox.event_type.like("infrastructure.%") | DomainEventOutbox.event_type.in_(D_EVENT_TYPES)))
        stamp = datetime.now()
        session.add(models.InfraNode(node_id="node_test", name="测试计算节点", agent_url="http://agent.test", status="READY", scheduling_paused=False, weight=100, labels_json={"zone": "test"}, cpu_total=8, memory_total_mb=8192, last_seen_at=stamp, created_at=stamp))
        session.add(models.InfraNodeHeartbeat(heartbeat_id="hbt_test", node_id="node_test", observed_at=stamp, cpu_available=8, memory_available_mb=8192, running_groups=0, image_digests_json=[DIGEST], detail_json={"engine": "linux test"}))
        session.add(models.InfraImage(image_id="img_test", name="测试 OpenSSL 镜像", tag="fixed", digest=DIGEST, size_bytes=100, scan_status="PASSED", startup_check_status="PASSED", teaching_validation_status="PASSED", enabled=True, created_at=stamp))
        session.commit()

    def override():
        with Session(engine) as session:
            yield session

    fake = FakeAgent()
    app.state.runtime_catalog = FakeCatalog()
    app.state.runtime_agent_factory = lambda _: fake
    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        yield engine, client, fake
    app.dependency_overrides.clear()
    del app.state.runtime_catalog
    del app.state.runtime_agent_factory
    with Session(engine) as session:
        for table in CLEAN_MODELS:
            session.execute(delete(table))
        session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.event_type.like("runtime.%") | DomainEventOutbox.event_type.like("checkpoint.%") | DomainEventOutbox.event_type.like("infrastructure.%") | DomainEventOutbox.event_type.in_(D_EVENT_TYPES)))
        session.commit()
    engine.dispose()


def start(client: TestClient, key: str = "runtime-start-student-001"):
    return client.post("/api/v1/runtime/start", headers={**STUDENT, "Idempotency-Key": key}, json={"lab_release_id": "release_rsa", "lab_version_id": "labv_rsa_v1", "course_id": "course_data_security", "class_id": "class_netsec_2301", "student_id": "student_2301001", "mode": "STUDENT"})


def test_start_is_idempotent_and_persists_scheduler_decision(db_and_client):
    engine, client, _ = db_and_client
    first, repeated = start(client), start(client)
    assert first.status_code == repeated.status_code == 201
    assert first.json()["runtime_request_id"] == repeated.json()["runtime_request_id"]
    assert first.json()["status"] == "RUNNING"
    instance_id = first.json()["instance_ids"][0]
    detail = client.get(f"/api/v1/runtime-instances/{instance_id}", headers=STUDENT)
    assert detail.status_code == 200
    assert detail.json()["scheduler"]["score"] > 0
    assert detail.json()["network_checks"]["lab-net-rsa"] == {"business_mysql": "DENY", "other_student": "DENY", "grader": "ALLOW_SAME_GROUP_ONLY"}
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.RuntimeRequest)) == 1
        assert session.scalar(select(func.count()).select_from(DomainEventOutbox).where(DomainEventOutbox.event_type == "lab.instance.started")) == 1


def test_student_scope_terminal_token_and_destroy_twice(db_and_client):
    _, client, fake = db_and_client
    started = start(client, "runtime-start-student-002").json()
    instance_id = next(instance_id for instance_id in started["instance_ids"] if client.get(f"/api/v1/runtime-instances/{instance_id}", headers=STUDENT).json()["role"] == "STUDENT_WORKSTATION")
    other = {**STUDENT, "X-User-Id": "other", "X-Student-Id": "student_other"}
    assert client.get(f"/api/v1/runtime-instances/{instance_id}", headers=other).status_code == 403
    token = client.post(f"/api/v1/runtime-instances/{instance_id}/terminal-token", headers=STUDENT, json={"idle_timeout_seconds": 300})
    assert token.status_code == 200 and "token" in token.json()
    assert "token=" not in token.json()["websocket_path"]
    destroyed = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "测试回收"})
    assert destroyed.status_code == 200 and destroyed.json()["status"] == "DESTROYED" and fake.destroyed
    repeated = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "重复回收"})
    assert repeated.status_code == 200 and repeated.json()["status"] == "DESTROYED"


def test_rsa_five_checkpoints_score_and_e_read_models(db_and_client):
    engine, client, _ = db_and_client
    instance_id = start(client, "runtime-start-student-003").json()["instance_ids"][0]
    result = client.post(f"/api/v1/runtime-instances/{instance_id}/rejudge", headers=STUDENT)
    assert result.status_code == 200
    assert len(result.json()["checkpoint_results"]) == 5
    assert result.json()["score"] == 100
    student = client.get("/api/v1/runtime/read-model/students/student_2301001", headers=STUDENT)
    assert student.status_code == 200 and student.json()["checkpoint_score_awarded"] == 100
    classroom = client.get("/api/v1/runtime/read-model/classes/class_netsec_2301", headers=TEACHER)
    assert classroom.status_code == 200 and classroom.json()["summary"]["RUNNING"] == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.CheckpointResult)) == 5
        assert session.scalar(select(func.count()).select_from(DomainEventOutbox).where(DomainEventOutbox.event_type.in_(["lab.checkpoint.passed", "lab.checkpoint.failed"]))) == 5
        checkpoint_events = list(session.scalars(
            select(DomainEventOutbox)
            .where(DomainEventOutbox.event_type.in_(["lab.checkpoint.passed", "lab.checkpoint.failed"]))
            .order_by(DomainEventOutbox.occurred_at, DomainEventOutbox.event_id)
        ))
        assert sorted(event.payload_json["raw_score"] for event in checkpoint_events) == [20, 40, 70, 90, 100]
        assert all(event.payload_json["max_score"] == 100 for event in checkpoint_events)


def test_no_capacity_returns_accepted_queue_fact(db_and_client):
    engine, client, fake = db_and_client
    fake.cpu_available = 0
    fake.memory_available_mb = 0
    response = start(client, "runtime-start-no-capacity")
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert response.json()["error"]["code"] == "RUNTIME.CAPACITY_UNAVAILABLE"
    canceled = client.post(f"/api/v1/runtime/requests/{response.json()['runtime_request_id']}/cancel", headers=STUDENT, json={"reason": "测试取消排队"})
    assert canceled.status_code == 200 and canceled.json()["status"] == "CANCELED"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.RuntimeQueue).where(models.RuntimeQueue.status == "CANCELED")) == 1


def test_teacher_class_scope_is_enforced(db_and_client):
    _, client, _ = db_and_client
    denied = client.get("/api/v1/runtime/read-model/classes/class_other", headers=TEACHER)
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH.CLASS_SCOPE_DENIED"


def test_e_facade_maps_permissions_and_submits_with_p0_event(db_and_client):
    engine, client, _ = db_and_client
    started = start(client, "runtime-start-e-facade")
    instance_id = next(instance_id for instance_id in started.json()["instance_ids"] if client.get(f"/api/v1/runtime-instances/{instance_id}", headers=STUDENT).json()["role"] == "STUDENT_WORKSTATION")
    e_headers = {"X-User-Id": "user_student_2301001", "X-Role": "student", "X-Student-Id": "student_2301001", "X-Permissions": "classroom.lab.read,classroom.lab.start,classroom.lab.submit,classroom.terminal.use", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301", "X-Service-Origin": "lab-classroom"}
    facade_start = client.post("/api/v1/runtime/lab-releases/release_rsa/start", headers=e_headers, json={"student_id": "student_2301001"})
    assert facade_start.status_code == 201 and facade_start.json()["runtime_request_id"] == started.json()["runtime_request_id"]
    detail = client.get(f"/api/v1/runtime/instances/{instance_id}", headers=e_headers)
    assert detail.status_code == 200
    assert {"lab_release_id", "course_id", "class_id", "student_id", "started_at", "last_activity_at"} <= detail.json().keys()
    token = client.post(f"/api/v1/runtime/instances/{instance_id}/terminal-token", headers=e_headers, json={"mode": "STUDENT"})
    assert token.status_code == 200 and token.json()["token_transport"] == "FIRST_FRAME"
    submitted = client.post("/api/v1/runtime/lab-releases/release_rsa/submit", headers=e_headers, json={"student_id": "student_2301001", "runtime_instance_id": instance_id})
    assert submitted.status_code == 200 and submitted.json()["submission_status"] == "SUBMITTED"
    with Session(engine) as session:
        event = session.scalar(select(DomainEventOutbox).where(DomainEventOutbox.event_type == "lab.submitted"))
        assert event and {"lab_release_id", "course_id", "class_id", "student_id", "runtime_instance_id", "status", "step", "score"} <= event.payload_json.keys()
