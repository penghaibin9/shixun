import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from time import sleep, time
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.common.errors import ApiError
from app.common.context import UserContext
from app.common.models import DomainEventOutbox, FileObject
from app.common.signed_capability import sign_capability, verify_capability
from app.labs.database import get_session
from app.main import app
from app.runtime import models
from app.runtime.service import RuntimeService

pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要真实 MySQL 8.4 的 YUEKE_DATABASE_URL")

STUDENT = {"X-User-Id": "user_student_2301001", "X-Role": "student", "X-Student-Id": "student_2301001", "X-Permissions": "runtime.read,runtime.start,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}
TEACHER = {"X-User-Id": "user_teacher_runtime", "X-Role": "teacher", "X-Teacher-Id": "teacher_runtime", "X-Permissions": "runtime.read,runtime.preview,runtime.destroy,runtime.rebuild,runtime.extend,runtime.rejudge,runtime.terminal,infrastructure.read,infrastructure.write", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}
ADMIN = {"X-User-Id": "user_admin_runtime", "X-Role": "admin", "X-Permissions": "infrastructure.read,infrastructure.write", "X-Course-Ids": "course_data_security", "X-Class-Ids": "class_netsec_2301"}
DIGEST = "sha256:" + "a" * 64
PCAP_PACKET = b"\x00\x01\x02\x03"
PCAP_BYTES = b"\xd4\xc3\xb2\xa1" + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 1) + struct.pack("<IIII", 1, 0, len(PCAP_PACKET), len(PCAP_PACKET)) + PCAP_PACKET
CLEAN_MODELS = [models.RuntimeCleanupTask, models.RuntimeAdminAction, models.CheckpointResult, models.RuntimeArtifact, models.RuntimeTerminalSession, models.RuntimeResourceUsage, models.RuntimeEvent, models.RuntimeNetwork, models.RuntimeContainer, models.RuntimeInstance, models.RuntimeInstanceGroup, models.RuntimeQueue, models.RuntimeRequest, models.RuntimeReleaseReadModel, models.InfraImageValidation, models.InfraImage, models.InfraNodeHeartbeat, models.InfraNode]
D_EVENT_TYPES = ["lab.instance.started", "lab.instance.failed", "lab.instance.destroyed", "lab.checkpoint.passed", "lab.checkpoint.failed", "lab.submitted"]


def capacity_facts(**overrides) -> dict:
    result = {
        "engine": "linux test",
        "cpu_total": 8,
        "memory_total_mb": 8192,
        "cpu_available": 8,
        "memory_available_mb": 8192,
        "running_groups": 0,
        "image_digests": [DIGEST],
    }
    result.update(overrides)
    return result


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
        self.destroyed_group_ids = []
        self.destroy_failures = 0
        self.invalid_destroy_response = False
        self.create_error = False
        self.invalid_create_response = False
        self.invalid_create_status = False
        self.duplicate_create_ids = False
        self.malformed_create_types = False
        self.capacity_response = None
        self.created_group_ids = []
        self.cpu_available = 8
        self.memory_available_mb = 8192
        self.destroy_delay_seconds = 0
        self.create_hook = None
        self.capture_start_failures = 0
        self.capture_stop_failures = 0
        self.capture_tampered = False
        self.captures = {}

    async def health(self):
        return {"status": "ok"}

    async def capacity(self):
        if self.capacity_response is not None:
            return self.capacity_response
        return capacity_facts(cpu_available=self.cpu_available, memory_available_mb=self.memory_available_mb)

    async def create_group(self, payload):
        self.created_group_ids.append(payload["runtime_group_id"])
        if self.create_error:
            raise ApiError("RUNTIME.PROVIDER_UNAVAILABLE", "测试节点代理不可用", 503)
        if self.invalid_create_response:
            return {"provider_group_id": payload["runtime_group_id"], "status": "RUNNING", "containers": [], "networks": []}
        containers = [{"container_id": f"container-{x['node_key']}", "name": x["node_key"], "node_key": x["node_key"]} for x in payload["containers"]]
        if self.duplicate_create_ids and len(containers) > 1:
            containers[1]["container_id"] = containers[0]["container_id"]
        if self.malformed_create_types:
            containers[0]["container_id"] = {"bad": "identifier"}
        if self.create_hook:
            self.create_hook(payload)
        return {"provider_group_id": payload["runtime_group_id"], "status": "STARTING" if self.invalid_create_status else "RUNNING", "containers": containers, "networks": [{"network_id": "network-rsa", "network_key": "lab-net-rsa", "isolation_checks": {"business_mysql": "DENY", "other_student": "DENY", "grader": "ALLOW_SAME_GROUP_ONLY"}}]}

    async def destroy(self, provider_group_id):
        self.destroyed_group_ids.append(provider_group_id)
        if self.destroy_delay_seconds:
            sleep(self.destroy_delay_seconds)
        if self.destroy_failures > 0:
            self.destroy_failures -= 1
            raise ApiError("RUNTIME.PROVIDER_UNAVAILABLE", "测试销毁失败", 503)
        self.destroyed = True
        if self.invalid_destroy_response:
            return {"provider_group_id": "wrong-group", "status": "DESTROYED"}
        return {"provider_group_id": provider_group_id, "status": "DESTROYED"}

    async def exec(self, provider_group_id, payload):
        return {"passed": True, "message": "检查点通过", "evidence": {"exit_code": 0, "provider_group_id": provider_group_id}}

    async def capture_start(self, provider_group_id):
        if self.capture_start_failures > 0:
            self.capture_start_failures -= 1
            raise ApiError("RUNTIME.PROVIDER_REJECTED", "测试抓包启动失败", 503)
        capture = self.captures.setdefault(provider_group_id, {
            "capture_id": f"cap_{sha256(provider_group_id.encode()).hexdigest()[:32]}",
            "started_at": "2026-09-22T00:00:00+00:00",
            "status": "CAPTURING",
        })
        return {
            "provider_group_id": provider_group_id, **capture,
            "idempotent_replay": capture["status"] != "CAPTURING",
        }

    async def capture_stop(self, provider_group_id):
        if self.capture_stop_failures > 0:
            self.capture_stop_failures -= 1
            raise ApiError("RUNTIME.PROVIDER_REJECTED", "测试抓包停止失败", 503)
        capture = self.captures.get(provider_group_id)
        if not capture:
            raise ApiError("RUNTIME.PROVIDER_REJECTED", "测试运行组未启动抓包", 503)
        capture["status"] = "COMPLETED"
        return {
            "provider_group_id": provider_group_id, **capture,
            "ended_at": "2026-09-22T00:01:00+00:00",
            "file_id": f"{capture['capture_id']}.pcap",
            "sha256": sha256(PCAP_BYTES).hexdigest(),
            "size_bytes": len(PCAP_BYTES),
            "packet_count": 1,
            "idempotent_replay": False,
        }

    async def capture_artifact(self, provider_group_id):
        capture = self.captures[provider_group_id]
        content = PCAP_BYTES + (b"tampered" if self.capture_tampered else b"")
        return {
            "content": content,
            "content_type": "application/vnd.tcpdump.pcap",
            "sha256": sha256(PCAP_BYTES).hexdigest(),
            "capture_id": capture["capture_id"],
            "content_length": str(len(PCAP_BYTES)),
        }


@pytest.fixture()
def db_and_client(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEKE_RUNTIME_ARTIFACT_DIR", str(tmp_path / "runtime-artifacts"))
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as session:
        for table in CLEAN_MODELS:
            session.execute(delete(table))
        session.execute(delete(FileObject).where(FileObject.bucket == "runtime-artifacts"))
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
        session.execute(delete(FileObject).where(FileObject.bucket == "runtime-artifacts"))
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


def test_capture_start_failure_rolls_back_and_never_reports_running(db_and_client):
    engine, client, fake = db_and_client
    fake.capture_start_failures = 1
    response = start(client, "runtime-start-capture-failure")
    assert response.status_code == 503
    assert response.json()["code"] == "RUNTIME.CAPTURE_START_FAILED"
    assert fake.destroyed_group_ids
    with Session(engine) as session:
        request = session.scalar(select(models.RuntimeRequest))
        group = session.scalar(select(models.RuntimeInstanceGroup))
        assert request.status == group.status == "FAILED"
        assert session.scalar(select(func.count()).select_from(models.RuntimeInstance)) == 0
        assert session.scalar(select(func.count()).select_from(models.RuntimeArtifact)) == 0


def test_student_scope_terminal_token_and_destroy_twice(db_and_client):
    engine, client, fake = db_and_client
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
    with Session(engine) as session:
        artifacts = list(session.scalars(select(models.RuntimeArtifact)))
        assert len(artifacts) == 1
        artifact = artifacts[0]
        file_object = session.get(FileObject, artifact.file_id)
        assert artifact.runtime_instance_id == instance_id
        assert artifact.sha256 == file_object.sha256 == sha256(PCAP_BYTES).hexdigest()
        assert artifact.size_bytes == file_object.size_bytes == len(PCAP_BYTES)
        assert file_object.storage_provider == "local" and file_object.bucket == "runtime-artifacts"
        assert (Path(os.environ["YUEKE_RUNTIME_ARTIFACT_DIR"]) / file_object.object_key).read_bytes() == PCAP_BYTES


def test_capture_integrity_failure_is_recorded_but_does_not_leak_group(db_and_client):
    engine, client, fake = db_and_client
    started = start(client, "runtime-start-capture-tamper").json()
    instance_id = next(
        value for value in started["instance_ids"]
        if client.get(f"/api/v1/runtime-instances/{value}", headers=STUDENT).json()["role"] == "STUDENT_WORKSTATION"
    )
    fake.capture_tampered = True
    destroyed = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "篡改抓包仍须清理"})
    assert destroyed.status_code == 200 and destroyed.json()["status"] == "DESTROYED"
    assert fake.destroyed
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.RuntimeArtifact)) == 0
        failure = session.scalar(select(models.RuntimeEvent).where(models.RuntimeEvent.event_type == "runtime.capture.failed"))
        assert failure and failure.detail_json["error_code"] == "RUNTIME.CAPTURE_ARTIFACT_INVALID"


def test_capture_stop_failure_does_not_block_destroy(db_and_client):
    engine, client, fake = db_and_client
    started = start(client, "runtime-start-capture-stop-failure").json()
    instance_id = started["instance_ids"][0]
    fake.capture_stop_failures = 1
    destroyed = client.post(
        f"/api/v1/runtime-instances/{instance_id}/destroy",
        headers=STUDENT,
        json={"reason": "抓包停止失败仍须清理"},
    )
    assert destroyed.status_code == 200 and destroyed.json()["status"] == "DESTROYED"
    assert fake.destroyed
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.RuntimeArtifact)) == 0
        failure = session.scalar(select(models.RuntimeEvent).where(models.RuntimeEvent.event_type == "runtime.capture.failed"))
        assert failure and failure.detail_json["error_code"] == "RUNTIME.PROVIDER_REJECTED"


def test_distributed_artifact_download_is_signed_scoped_short_lived_and_idempotent(db_and_client, monkeypatch, tmp_path):
    engine, client, _ = db_and_client
    secret = "test-log-distribution-signing-key-32-bytes"
    storage_secret = "test-artifact-storage-signing-key-32-bytes"
    storage_root = tmp_path / "runtime-artifacts"
    storage_root.mkdir()
    artifact_bytes = b"PCAP\r\nreal-distributed-capture\x00\x01"
    artifact_path = storage_root / "file-distributed-1"
    artifact_path.write_bytes(artifact_bytes)
    monkeypatch.setenv("YUEKE_LOG_DISTRIBUTION_SIGNING_KEY", secret)
    monkeypatch.setenv("YUEKE_ARTIFACT_STORAGE_SIGNING_KEY", storage_secret)
    monkeypatch.setenv("YUEKE_ARTIFACT_DOWNLOAD_BASE_URL", "http://testserver/api/v1/artifact-storage")
    monkeypatch.setenv("YUEKE_RUNTIME_ARTIFACT_DIR", str(storage_root))
    started = start(client, "runtime-start-distributed-artifact").json()
    instance_id = next(
        item_id for item_id in started["instance_ids"]
        if client.get(f"/api/v1/runtime-instances/{item_id}", headers=STUDENT).json()["role"] == "STUDENT_WORKSTATION"
    )
    with Session(engine) as session:
        session.add(FileObject(
            file_id="file-distributed-1",
            storage_provider="local",
            bucket="runtime-artifacts",
            object_key="file-distributed-1",
            original_name="../../capture.pcap",
            mime_type="application/vnd.tcpdump.pcap",
            size_bytes=len(artifact_bytes),
            sha256=sha256(artifact_bytes).hexdigest(),
            created_by="service_node_agent",
            created_at=datetime.utcnow(),
        ))
        session.add(models.RuntimeArtifact(
            runtime_artifact_id="artifact-distributed-1",
            runtime_instance_id=instance_id,
            student_id="student_2301001",
            artifact_type="TRAFFIC",
            file_id="file-distributed-1",
            sha256=sha256(artifact_bytes).hexdigest(),
            size_bytes=len(artifact_bytes),
            capture_started_at=datetime.utcnow(),
            capture_ended_at=datetime.utcnow(),
        ))
        session.commit()

    issued_at = int(time())
    claims = {
        "version": 1,
        "issuer": "lab-classroom",
        "audience": "lab-runtime",
        "assignment_id": "assignment-recipient-1",
        "distribution_id": "distribution-a",
        "distribution_type": "TRAFFIC",
        "student_id": "student_recipient",
        "course_id": "course_data_security",
        "class_id": "class_netsec_2301",
        "lab_release_id": "release_rsa",
        "reference_ids": ["artifact-distributed-1"],
        "nonce": "nonce-distribution-download-1",
        "issued_at": issued_at,
        "expires_at": issued_at + 60,
    }
    authorization = sign_capability(claims, secret)
    recipient = {
        "X-User-Id": "user_recipient",
        "X-Role": "student",
        "X-Student-Id": "student_recipient",
        "X-Permissions": "classroom.logs.assignment.download,runtime.read",
        "X-Course-Ids": "course_data_security",
        "X-Class-Ids": "class_netsec_2301",
        "X-Service-Origin": "lab-classroom",
    }

    first = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=recipient,
        json={"authorization": authorization},
    )
    replay = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=recipient,
        json={"authorization": authorization},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["artifact_count"] == 1 and first.json()["status"] == "READY"
    assert first.json()["download_url"].startswith("http://testserver/api/v1/artifact-storage/bundles/assignment-recipient-1?capability=")
    parsed_download = urlparse(first.json()["download_url"])
    storage_capability = parse_qs(parsed_download.query)["capability"][0]
    downloaded = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=recipient)
    downloaded_again = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=recipient)
    assert downloaded.status_code == downloaded_again.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert downloaded.headers["cache-control"] == "no-store"
    with ZipFile(BytesIO(downloaded.content)) as archive:
        assert len(archive.namelist()) == 1
        entry_name = archive.namelist()[0]
        assert ".." not in entry_name and "/" not in entry_name and "\\" not in entry_name
        assert archive.read(entry_name) == artifact_bytes
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DomainEventOutbox).where(
            DomainEventOutbox.event_type == "runtime.artifact.distribution_download_authorized",
            DomainEventOutbox.idempotency_key == "assignment-recipient-1:nonce-distribution-download-1",
        )) == 1
        assert session.scalar(select(func.count()).select_from(DomainEventOutbox).where(
            DomainEventOutbox.event_type == "runtime.artifact.distribution_bundle_downloaded",
            DomainEventOutbox.idempotency_key == "assignment-recipient-1:nonce-distribution-download-1",
        )) == 1

    wrong_assignment = client.get(
        f"/api/v1/artifact-storage/bundles/assignment-other?capability={storage_capability}",
        headers=recipient,
    )
    assert wrong_assignment.status_code == 403 and wrong_assignment.json()["code"] == "RUNTIME.ARTIFACT_ASSIGNMENT_MISMATCH"

    storage_claims = verify_capability(storage_capability, storage_secret)
    expired_storage_claims = {**storage_claims, "issued_at": issued_at - 120, "expires_at": issued_at - 60}
    expired_storage = client.get(
        f"/api/v1/artifact-storage/bundles/assignment-recipient-1?capability={sign_capability(expired_storage_claims, storage_secret)}",
        headers=recipient,
    )
    assert expired_storage.status_code == 403 and expired_storage.json()["code"] == "RUNTIME.ARTIFACT_STORAGE_CAPABILITY_EXPIRED"

    wrong_audience_claims = {**storage_claims, "audience": "lab-runtime"}
    wrong_audience = client.get(
        f"/api/v1/artifact-storage/bundles/assignment-recipient-1?capability={sign_capability(wrong_audience_claims, storage_secret)}",
        headers=recipient,
    )
    assert wrong_audience.status_code == 403 and wrong_audience.json()["code"] == "RUNTIME.ARTIFACT_STORAGE_CAPABILITY_INVALID"

    wrong_reference_digest_claims = {**storage_claims, "reference_digest": "0" * 64}
    wrong_reference_digest = client.get(
        f"/api/v1/artifact-storage/bundles/assignment-recipient-1?capability={sign_capability(wrong_reference_digest_claims, storage_secret)}",
        headers=recipient,
    )
    assert wrong_reference_digest.status_code == 403 and wrong_reference_digest.json()["code"] == "RUNTIME.ARTIFACT_REFERENCE_SET_INVALID"

    encoded_storage, storage_signature = storage_capability.split(".", 1)
    tampered_storage_payload = json.loads(urlsafe_b64decode(encoded_storage + "=" * (-len(encoded_storage) % 4)))
    tampered_storage_payload["assignment_id"] = "assignment-other"
    tampered_storage_encoded = urlsafe_b64encode(json.dumps(tampered_storage_payload, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=").decode()
    tampered_storage = client.get(
        f"/api/v1/artifact-storage/bundles/assignment-other?capability={tampered_storage_encoded}.{storage_signature}",
        headers=recipient,
    )
    assert tampered_storage.status_code == 403 and tampered_storage.json()["code"] == "RUNTIME.ARTIFACT_STORAGE_CAPABILITY_INVALID"

    artifact_path.write_bytes(b"X" * len(artifact_bytes))
    corrupt = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=recipient)
    assert corrupt.status_code == 409 and corrupt.json()["code"] == "RUNTIME.ARTIFACT_INTEGRITY_FAILED"
    artifact_path.write_bytes(artifact_bytes)

    outside_path = tmp_path / "outside.pcap"
    outside_path.write_bytes(artifact_bytes)
    with Session(engine) as session:
        file_object = session.get(FileObject, "file-distributed-1")
        file_object.object_key = str(outside_path)
        session.commit()
    escaped_path = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=recipient)
    assert escaped_path.status_code == 409 and escaped_path.json()["code"] == "RUNTIME.ARTIFACT_PATH_INVALID"
    with Session(engine) as session:
        file_object = session.get(FileObject, "file-distributed-1")
        file_object.object_key = "file-distributed-1"
        session.commit()

    artifact_path.unlink()
    missing_file = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=recipient)
    assert missing_file.status_code == 404 and missing_file.json()["code"] == "RUNTIME.ARTIFACT_FILE_MISSING"
    artifact_path.write_bytes(artifact_bytes)

    direct_owner = client.post(
        "/api/v1/runtime/log-artifacts/bundle-url",
        headers=STUDENT,
        json={"artifact_ids": ["artifact-distributed-1"]},
    )
    assert direct_owner.status_code == 200
    assert direct_owner.json()["status"] == "READY" and "/bundles/pending" not in direct_owner.json()["download_url"]
    direct_url = urlparse(direct_owner.json()["download_url"])
    direct_download = client.get(f"{direct_url.path}?{direct_url.query}", headers=STUDENT)
    assert direct_download.status_code == 200
    with ZipFile(BytesIO(direct_download.content)) as archive:
        assert archive.read(archive.namelist()[0]) == artifact_bytes
    direct_other = client.get(f"{direct_url.path}?{direct_url.query}", headers={**STUDENT, "X-User-Id": "user_other", "X-Student-Id": "student_other"})
    assert direct_other.status_code == 403
    other_class_teacher = client.post(
        "/api/v1/runtime/log-artifacts/bundle-url",
        headers={**TEACHER, "X-Class-Ids": "class_other"},
        json={"artifact_ids": ["artifact-distributed-1"]},
    )
    assert other_class_teacher.status_code == 403 and other_class_teacher.json()["code"] == "AUTH.CLASS_SCOPE_DENIED"

    single_owner = client.post(
        "/api/v1/runtime/log-artifacts/artifact-distributed-1/download-url",
        headers=STUDENT,
    )
    assert single_owner.status_code == 200 and single_owner.json()["status"] == "READY"

    with Session(engine) as session:
        session.execute(delete(FileObject).where(FileObject.file_id == "file-distributed-1"))
        session.commit()
    missing_registration = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=recipient)
    assert missing_registration.status_code == 409 and missing_registration.json()["code"] == "RUNTIME.ARTIFACT_FILE_OBJECT_MISSING"
    with Session(engine) as session:
        session.add(FileObject(
            file_id="file-distributed-1",
            storage_provider="local",
            bucket="runtime-artifacts",
            object_key="file-distributed-1",
            original_name="../../capture.pcap",
            mime_type="application/vnd.tcpdump.pcap",
            size_bytes=len(artifact_bytes),
            sha256=sha256(artifact_bytes).hexdigest(),
            created_by="service_node_agent",
            created_at=datetime.utcnow(),
        ))
        session.commit()

    # The ordinary artifact API still enforces ownership and cannot be used as
    # a blanket escape hatch by a distribution recipient.
    direct = client.post(
        "/api/v1/runtime/log-artifacts/bundle-url",
        headers=recipient,
        json={"artifact_ids": ["artifact-distributed-1"]},
    )
    assert direct.status_code == 403 and direct.json()["code"] == "AUTH.STUDENT_SCOPE_DENIED"

    other_student = {**recipient, "X-User-Id": "user_other", "X-Student-Id": "student_other"}
    crossed = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=other_student,
        json={"authorization": authorization},
    )
    assert crossed.status_code == 403 and crossed.json()["code"] == "AUTH.STUDENT_SCOPE_DENIED"
    crossed_download = client.get(f"{parsed_download.path}?{parsed_download.query}", headers=other_student)
    assert crossed_download.status_code == 403 and crossed_download.json()["code"] == "AUTH.STUDENT_SCOPE_DENIED"

    # Rebinding the signed assignment/distribution payload or artifact set
    # invalidates the signature, so another distribution cannot borrow it.
    encoded, signature = authorization.split(".", 1)
    payload = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["distribution_id"] = "distribution-b"
    payload["reference_ids"] = ["artifact-other"]
    tampered_encoded = urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=").decode()
    tampered = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=recipient,
        json={"authorization": f"{tampered_encoded}.{signature}"},
    )
    assert tampered.status_code == 403 and tampered.json()["code"] == "RUNTIME.DISTRIBUTION_AUTH_INVALID"

    expired_claims = {**claims, "nonce": "nonce-distribution-expired-1", "issued_at": issued_at - 180, "expires_at": issued_at - 120}
    expired = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=recipient,
        json={"authorization": sign_capability(expired_claims, secret)},
    )
    assert expired.status_code == 403 and expired.json()["code"] == "RUNTIME.DISTRIBUTION_AUTH_EXPIRED"

    wrong_scope_claims = {**claims, "nonce": "nonce-distribution-wrong-scope", "class_id": "class_other"}
    wrong_scope_headers = {**recipient, "X-Class-Ids": "class_netsec_2301,class_other"}
    wrong_scope = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=wrong_scope_headers,
        json={"authorization": sign_capability(wrong_scope_claims, secret)},
    )
    assert wrong_scope.status_code == 403 and wrong_scope.json()["code"] == "RUNTIME.DISTRIBUTION_SOURCE_SCOPE_MISMATCH"

    wrong_release_claims = {**claims, "nonce": "nonce-distribution-wrong-release", "lab_release_id": "release_other"}
    wrong_release = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=recipient,
        json={"authorization": sign_capability(wrong_release_claims, secret)},
    )
    assert wrong_release.status_code == 403
    assert wrong_release.json()["code"] == "RUNTIME.DISTRIBUTION_SOURCE_SCOPE_MISMATCH"

    with Session(engine) as session:
        event_id = session.scalar(select(models.RuntimeEvent.runtime_event_id).where(
            models.RuntimeEvent.runtime_group_id == started["runtime_group_id"]
        ).limit(1))
    assert event_id
    audit_claims = {
        **claims,
        "assignment_id": "assignment-audit-recipient",
        "distribution_id": "distribution-audit",
        "distribution_type": "AUDIT",
        "reference_ids": [event_id],
        "nonce": "nonce-distribution-audit-1",
    }
    audit_download = client.post(
        "/api/v1/runtime/log-artifacts/distribution-bundle-url",
        headers=recipient,
        json={"authorization": sign_capability(audit_claims, secret)},
    )
    assert audit_download.status_code == 200
    assert audit_download.json()["artifact_count"] == 1 and audit_download.json()["status"] == "READY"
    audit_url = urlparse(audit_download.json()["download_url"])
    audit_bundle = client.get(f"{audit_url.path}?{audit_url.query}", headers=recipient)
    assert audit_bundle.status_code == 200
    with ZipFile(BytesIO(audit_bundle.content)) as archive:
        audit_payload = json.loads(archive.read(archive.namelist()[0]))
        assert audit_payload["event_id"] == event_id
        assert audit_payload["class_id"] == "class_netsec_2301"


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


def test_admin_heartbeat_refresh_is_scoped_and_idempotent(db_and_client):
    engine, client, _ = db_and_client
    denied = client.post(
        "/api/v1/infrastructure/nodes/node_test/heartbeat",
        headers={**TEACHER, "Idempotency-Key": "heartbeat-denied-001"},
    )
    assert denied.status_code == 403 and denied.json()["code"] == "AUTH.ADMIN_REQUIRED"

    headers = {**ADMIN, "Idempotency-Key": "heartbeat-refresh-001"}
    first = client.post("/api/v1/infrastructure/nodes/node_test/heartbeat", headers=headers)
    repeated = client.post("/api/v1/infrastructure/nodes/node_test/heartbeat", headers=headers)
    assert first.status_code == repeated.status_code == 200
    assert first.json()["status"] == repeated.json()["status"] == "READY"
    assert first.json()["idempotent_replay"] is False
    assert repeated.json()["idempotent_replay"] is True
    conflict = client.post(
        "/api/v1/infrastructure/nodes/node_other/heartbeat",
        headers=headers,
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "RUNTIME.IDEMPOTENCY_KEY_CONFLICT"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.InfraNodeHeartbeat)) == 2
        assert session.scalar(select(func.count()).select_from(models.RuntimeEvent).where(models.RuntimeEvent.event_type == "runtime.node.heartbeat.completed")) == 1


def test_invalid_capacity_is_rejected_before_node_registration(db_and_client):
    engine, client, fake = db_and_client
    fake.capacity_response = capacity_facts(memory_total_mb=2_147_483_648, memory_available_mb=2_147_483_648)
    response = client.post("/api/v1/infrastructure/nodes", headers=ADMIN, json={
        "node_id": "node_invalid_capacity",
        "name": "非法容量节点",
        "agent_url": "http://invalid-capacity.test",
        "weight": 100,
        "labels": {},
    })
    assert response.status_code == 503
    assert response.json()["code"] == "RUNTIME.NODE_RESPONSE_INVALID"
    with Session(engine) as session:
        assert session.get(models.InfraNode, "node_invalid_capacity") is None


def test_invalid_capacity_heartbeat_freezes_failure_instead_of_leaving_action_running(db_and_client):
    engine, client, fake = db_and_client
    fake.capacity_response = capacity_facts(running_groups=2_147_483_648)
    headers = {**ADMIN, "Idempotency-Key": "heartbeat-invalid-capacity"}
    first = client.post("/api/v1/infrastructure/nodes/node_test/heartbeat", headers=headers)
    repeated = client.post("/api/v1/infrastructure/nodes/node_test/heartbeat", headers=headers)
    assert first.status_code == repeated.status_code == 503
    assert first.json()["code"] == repeated.json()["code"] == "RUNTIME.NODE_RESPONSE_INVALID"
    assert repeated.json()["details"]["idempotent_replay"] is True
    with Session(engine) as session:
        action = session.scalar(select(models.RuntimeAdminAction).where(
            models.RuntimeAdminAction.idempotency_key == "heartbeat-invalid-capacity"
        ))
        assert action.status == "FAILED"
        assert session.get(models.InfraNode, "node_test").status == "OFFLINE"
        assert session.scalar(select(func.count()).select_from(models.InfraNodeHeartbeat)) == 1


def test_admin_action_key_is_unique_across_concurrent_targets(db_and_client):
    engine, client, _ = db_and_client
    stamp = datetime.utcnow()
    with Session(engine) as session:
        session.add(models.InfraNode(node_id="node_other", name="其他测试节点", agent_url="http://agent-other.test", status="READY", scheduling_paused=False, weight=100, labels_json={}, cpu_total=8, memory_total_mb=8192, last_seen_at=stamp, created_at=stamp))
        session.commit()

    def heartbeat(node_id: str):
        return client.post(
            f"/api/v1/infrastructure/nodes/{node_id}/heartbeat",
            headers={**ADMIN, "Idempotency-Key": "concurrent-cross-target-key"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(heartbeat, ["node_test", "node_other"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert next(response for response in responses if response.status_code == 409).json()["code"] == "RUNTIME.IDEMPOTENCY_KEY_CONFLICT"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.RuntimeAdminAction).where(models.RuntimeAdminAction.idempotency_key == "concurrent-cross-target-key")) == 1
        assert session.scalar(select(func.count()).select_from(models.InfraNodeHeartbeat)) == 2


def test_admin_queue_retry_recovers_capacity_and_is_idempotent(db_and_client):
    engine, client, fake = db_and_client
    fake.cpu_available = 0
    fake.memory_available_mb = 0
    queued_response = start(client, "runtime-start-recovery-queue")
    assert queued_response.status_code == 202 and queued_response.json()["status"] == "QUEUED"
    with Session(engine) as session:
        queued = session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == queued_response.json()["runtime_request_id"]))
        queue_id = queued.queue_id

    denied = client.post(
        f"/api/v1/infrastructure/queue/{queue_id}/retry",
        headers={**TEACHER, "Idempotency-Key": "queue-retry-denied-001"},
    )
    assert denied.status_code == 403 and denied.json()["code"] == "AUTH.ADMIN_REQUIRED"

    fake.cpu_available = 8
    fake.memory_available_mb = 8192
    headers = {**ADMIN, "Idempotency-Key": "queue-retry-capacity-001"}
    first = client.post(f"/api/v1/infrastructure/queue/{queue_id}/retry", headers=headers)
    assert first.status_code == 200 and first.json()["status"] == "RUNNING"
    with Session(engine) as session:
        request = session.scalar(select(models.RuntimeRequest).where(models.RuntimeRequest.runtime_request_id == queued_response.json()["runtime_request_id"]))
        request.status = "CANCELED"
        session.commit()
    repeated = client.post(f"/api/v1/infrastructure/queue/{queue_id}/retry", headers=headers)
    assert repeated.status_code == 200 and repeated.json()["status"] == "RUNNING"
    assert first.json()["idempotent_replay"] is False
    assert repeated.json()["idempotent_replay"] is True
    with Session(engine) as session:
        queue = session.get(models.RuntimeQueue, queue_id)
        assert queue.status == "DONE" and queue.attempts == 1
        assert session.scalar(select(func.count()).select_from(models.RuntimeInstanceGroup)) == 1


def test_admin_queue_retry_replays_the_same_provider_error(db_and_client):
    engine, client, fake = db_and_client
    fake.cpu_available = 0
    fake.memory_available_mb = 0
    queued_response = start(client, "runtime-start-retry-error")
    with Session(engine) as session:
        queue_id = session.scalar(select(models.RuntimeQueue.queue_id).where(models.RuntimeQueue.runtime_request_id == queued_response.json()["runtime_request_id"]))
    fake.cpu_available = 8
    fake.memory_available_mb = 8192
    fake.create_error = True
    headers = {**ADMIN, "Idempotency-Key": "queue-retry-error-001"}
    first = client.post(f"/api/v1/infrastructure/queue/{queue_id}/retry", headers=headers)
    repeated = client.post(f"/api/v1/infrastructure/queue/{queue_id}/retry", headers=headers)
    assert first.status_code == repeated.status_code == 503
    assert first.json()["code"] == repeated.json()["code"] == "RUNTIME.PROVIDER_UNAVAILABLE"
    assert repeated.json()["details"]["idempotent_replay"] is True
    with Session(engine) as session:
        assert session.get(models.RuntimeQueue, queue_id).attempts == 1


def test_admin_maintenance_marks_stale_nodes_recovers_queue_and_reclaims_expired_group(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-expiry-001").json()
    fake.cpu_available = 0
    fake.memory_available_mb = 0
    queued = start(client, "runtime-start-interrupted-001").json()
    old = datetime.utcnow() - timedelta(minutes=10)
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        group.expires_at = old
        group.provider_group_id = None
        for item in session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)):
            item.expires_at = old
        node = session.get(models.InfraNode, "node_test")
        node.last_seen_at = old
        queue = session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == queued["runtime_request_id"]))
        queue.status = "PROCESSING"
        queue.enqueued_at = old
        request = session.get(models.RuntimeRequest, queued["runtime_request_id"])
        request.status = "SCHEDULING"
        session.commit()
        queue_id = queue.queue_id

    headers = {**ADMIN, "Idempotency-Key": "maintenance-recovery-001"}
    body = {"node_timeout_seconds": 90, "processing_timeout_seconds": 120, "retry_limit": 1, "expiry_limit": 1, "max_queue_attempts": 5}
    first = client.post("/api/v1/infrastructure/maintenance/run", headers=headers, json=body)
    repeated = client.post("/api/v1/infrastructure/maintenance/run", headers=headers, json=body)
    assert first.status_code == repeated.status_code == 200
    assert first.json()["automatic"] is False
    assert first.json()["node_timeouts"] == ["node_test"]
    assert first.json()["processing_recovered"] == [queue_id]
    assert first.json()["expiry_results"] == [{"runtime_group_id": running["runtime_group_id"], "status": "DESTROYED"}]
    assert first.json()["queue_results"] == [{"queue_id": queue_id, "status": "QUEUED"}]
    assert repeated.json()["idempotent_replay"] is True
    conflict = client.post(
        "/api/v1/infrastructure/maintenance/run",
        headers=headers,
        json={**body, "retry_limit": 2},
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "RUNTIME.IDEMPOTENCY_KEY_CONFLICT"
    with Session(engine) as session:
        assert session.get(models.InfraNode, "node_test").status == "OFFLINE"
        assert session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).status == "DESTROYED"
        assert session.get(models.RuntimeQueue, queue_id).status == "WAITING"
        assert session.scalar(select(func.count()).select_from(models.RuntimeEvent).where(models.RuntimeEvent.event_type == "runtime.maintenance.completed")) == 1
    assert running["runtime_group_id"] in fake.destroyed_group_ids


def test_expiry_cleanup_failure_stays_retryable_until_destroy_succeeds(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-cleanup-retry").json()
    old = datetime.utcnow() - timedelta(minutes=10)
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        group.expires_at = old
        group.provider_group_id = None
        session.commit()
    fake.destroy_failures = 1
    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    first = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "cleanup-retry-first"}, json=body)
    assert first.status_code == 200
    assert first.json()["status"] == "COMPLETED_WITH_ERRORS"
    assert first.json()["expiry_results"] == [{"runtime_group_id": running["runtime_group_id"], "status": "DESTROYING", "error_code": "RUNTIME.EXPIRY_CLEANUP_FAILED"}]
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        assert group.status == "DESTROYING" and group.cleanup_attempts == 1
        group.cleanup_not_before = old
        session.commit()
    second = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "cleanup-retry-second"}, json=body)
    assert second.status_code == 200
    assert second.json()["expiry_results"] == [{"runtime_group_id": running["runtime_group_id"], "status": "DESTROYED"}]
    with Session(engine) as session:
        assert session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).status == "DESTROYED"
    assert fake.destroyed_group_ids.count(running["runtime_group_id"]) == 2


def test_concurrent_maintenance_destroys_expired_group_once(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-concurrent-cleanup").json()
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        group.expires_at = datetime.utcnow() - timedelta(minutes=1)
        session.commit()
    fake.destroy_delay_seconds = 0.2
    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}

    def maintain(key: str):
        return client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": key}, json=body)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(maintain, ["cleanup-concurrent-a", "cleanup-concurrent-b"]))
    assert [response.status_code for response in responses] == [200, 200]
    expiry_results = [item for response in responses for item in response.json()["expiry_results"]]
    assert expiry_results == [{"runtime_group_id": running["runtime_group_id"], "status": "DESTROYED"}]
    assert fake.destroyed_group_ids.count(running["runtime_group_id"]) == 1
    with Session(engine) as session:
        assert session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).status == "DESTROYED"
        assert session.scalar(select(func.count()).select_from(DomainEventOutbox).where(
            DomainEventOutbox.idempotency_key == f"lab.instance.destroyed:{running['runtime_group_id']}:g1"
        )) == 1


def test_invalid_manual_destroy_response_is_recovered_by_maintenance(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-manual-cleanup-recovery").json()
    instance_id = running["instance_ids"][0]
    fake.invalid_destroy_response = True
    failed = client.post(
        f"/api/v1/runtime-instances/{instance_id}/destroy",
        headers=STUDENT,
        json={"reason": "人工停止"},
    )
    assert failed.status_code == 503
    assert failed.json()["code"] == "RUNTIME.PROVIDER_RESPONSE_INVALID"
    fake.invalid_destroy_response = False
    old = datetime.utcnow() - timedelta(minutes=1)
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        assert group.status == "DESTROYING" and group.cleanup_intent == "MANUAL" and group.cleanup_owner is None
        group.cleanup_not_before = old
        session.commit()

    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    recovered = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "recover-manual-cleanup"}, json=body)
    assert recovered.status_code == 200
    assert recovered.json()["expiry_results"] == [{"runtime_group_id": running["runtime_group_id"], "status": "DESTROYED"}]
    with Session(engine) as session:
        assert session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).status == "DESTROYED"
        assert session.get(models.RuntimeRequest, running["runtime_request_id"]).status == "CANCELED"
    assert fake.destroyed_group_ids.count(running["runtime_group_id"]) == 2


def test_expired_admin_action_freezes_interrupted_failure(db_and_client):
    engine, client, _ = db_and_client
    stamp = datetime.utcnow() - timedelta(minutes=10)
    with Session(engine) as session:
        session.add(models.RuntimeAdminAction(
            action_id="raa_expired_test", actor_user_id=ADMIN["X-User-Id"], idempotency_key="expired-heartbeat-key",
            action_type="NODE_HEARTBEAT", target_id="node_test", request_json={}, status="IN_PROGRESS",
            owner_token="expired-owner", generation=1, lease_expires_at=stamp, result_json=None,
            error_code=None, error_message=None, error_status_code=None, created_at=stamp, updated_at=stamp,
        ))
        session.commit()
    response = client.post("/api/v1/infrastructure/nodes/node_test/heartbeat", headers={**ADMIN, "Idempotency-Key": "expired-heartbeat-key"})
    assert response.status_code == 503
    assert response.json()["code"] == "RUNTIME.RECOVERY_INTERRUPTED"
    assert response.json()["details"]["idempotent_replay"] is True


def test_expired_action_and_queue_leases_cannot_be_revived(db_and_client):
    engine, client, fake = db_and_client
    fake.cpu_available = 0
    fake.memory_available_mb = 0
    pending = start(client, "runtime-start-expired-lease").json()
    expired = datetime.utcnow() - timedelta(seconds=1)
    future = datetime.utcnow() + timedelta(minutes=5)
    context = UserContext(
        ADMIN["X-User-Id"], "admin", None, None,
        frozenset({"infrastructure.read", "infrastructure.write"}),
        frozenset({"course_data_security"}), frozenset({"class_netsec_2301"}),
    )
    with Session(engine) as session:
        action = models.RuntimeAdminAction(
            action_id="raa_expired_renew", actor_user_id=context.user_id, idempotency_key="expired-renew",
            action_type="QUEUE_RETRY", target_id="queue", request_json={}, status="IN_PROGRESS",
            owner_token="expired-action-owner", generation=7, lease_expires_at=expired, result_json=None,
            error_code=None, error_message=None, error_status_code=None, error_details_json=None,
            created_at=expired, updated_at=expired,
        )
        session.add(action)
        session.commit()
        service = RuntimeService(session, context, agent_factory=lambda _: fake)
        with pytest.raises(ApiError) as action_error:
            service._renew_admin_action(action)
        assert action_error.value.code == "RUNTIME.RECOVERY_LEASE_LOST"
        session.rollback()

        action.lease_expires_at = future
        queue = session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == pending["runtime_request_id"]))
        queue.status = "PROCESSING"
        queue.processing_owner = action.owner_token
        queue.lease_expires_at = expired
        session.commit()
        stored_expiry = queue.lease_expires_at
        with pytest.raises(ApiError) as queue_error:
            service._renew_queue_lease(pending["runtime_request_id"], action.owner_token)
        assert queue_error.value.code == "RUNTIME.QUEUE_LEASE_LOST"
        session.rollback()
        assert session.get(models.RuntimeQueue, queue.queue_id).lease_expires_at == stored_expiry


def test_failed_provision_rollback_is_recovered_without_expiry_cancel(db_and_client):
    engine, client, fake = db_and_client
    fake.invalid_create_response = True
    fake.destroy_failures = 1
    failed = start(client, "runtime-start-invalid-provider")
    assert failed.status_code == 503
    assert failed.json()["code"] == "RUNTIME.PROVISION_ROLLBACK_FAILED"
    with Session(engine) as session:
        group = session.scalar(select(models.RuntimeInstanceGroup))
        request_id = group.runtime_request_id
        cleanup_task = session.scalar(select(models.RuntimeCleanupTask))
        assert group.status == "FAILED" and group.cleanup_intent is None
        assert cleanup_task.status == "WAITING" and cleanup_task.intent == "PROVISION_ORPHAN"
        cleanup_task.not_before = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
        group_id = group.runtime_group_id

    fake.invalid_create_response = False
    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    response = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "recover-provision-rollback"}, json=body)
    assert response.status_code == 200
    assert response.json()["expiry_results"] == [{"runtime_group_id": group_id, "status": "ORPHAN_CLEANED", "cleanup_intent": "PROVISION_ORPHAN"}]
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, group_id)
        request = session.get(models.RuntimeRequest, request_id)
        assert group.status == "FAILED" and group.cleanup_intent is None
        assert request.status == "FAILED"
        assert session.scalar(select(models.RuntimeCleanupTask.status)) == "DONE"
    assert fake.destroyed_group_ids.count(group_id) == 2


def test_queue_retry_uses_new_provider_generation_while_old_cleanup_is_backing_off(db_and_client):
    engine, client, fake = db_and_client
    fake.invalid_create_response = True
    fake.destroy_failures = 1
    failed = start(client, "runtime-start-generation-failover")
    assert failed.status_code == 503
    with Session(engine) as session:
        group = session.scalar(select(models.RuntimeInstanceGroup))
        request = session.get(models.RuntimeRequest, group.runtime_request_id)
        task = session.scalar(select(models.RuntimeCleanupTask))
        old_provider_group_id = task.provider_group_id
        task.not_before = datetime.utcnow() - timedelta(seconds=1)
        request.status = "QUEUED"
        session.add(models.RuntimeQueue(
            queue_id="rtq_generation_failover", runtime_request_id=request.runtime_request_id,
            status="WAITING", priority=100, attempts=0, not_before=None,
            processing_owner=None, lease_expires_at=None, enqueued_at=datetime.utcnow(),
        ))
        session.commit()

    fake.invalid_create_response = False
    fake.destroy_failures = 1
    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 1, "expiry_limit": 5, "max_queue_attempts": 5}
    recovered = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "generation-failover-retry"}, json=body)
    assert recovered.status_code == 200
    assert recovered.json()["queue_results"] == [{"queue_id": "rtq_generation_failover", "status": "RUNNING"}]
    with Session(engine) as session:
        group = session.scalar(select(models.RuntimeInstanceGroup))
        task = session.scalar(select(models.RuntimeCleanupTask))
        new_provider_group_id = group.provider_group_id
        assert group.status == "RUNNING" and group.provider_generation == 2
        assert new_provider_group_id != old_provider_group_id
        assert task.status == "WAITING"
        task.not_before = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
    assert new_provider_group_id not in fake.destroyed_group_ids

    cleaned = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "generation-failover-cleanup"}, json={**body, "retry_limit": 0})
    assert cleaned.status_code == 200
    with Session(engine) as session:
        group = session.scalar(select(models.RuntimeInstanceGroup))
        assert group.status == "RUNNING" and group.provider_group_id == new_provider_group_id
        assert session.scalar(select(models.RuntimeCleanupTask.status)) == "DONE"
    assert old_provider_group_id in fake.destroyed_group_ids
    assert new_provider_group_id not in fake.destroyed_group_ids


def test_queue_retry_exhaustion_updates_request_and_replays_error(db_and_client):
    engine, client, fake = db_and_client
    fake.cpu_available = 0
    fake.memory_available_mb = 0
    queued_response = start(client, "runtime-start-exhausted").json()
    with Session(engine) as session:
        queue = session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == queued_response["runtime_request_id"]))
        queue.attempts = 5
        queue_id = queue.queue_id
        session.commit()
    headers = {**ADMIN, "Idempotency-Key": "queue-exhausted-key"}
    first = client.post(f"/api/v1/infrastructure/queue/{queue_id}/retry", headers=headers)
    repeated = client.post(f"/api/v1/infrastructure/queue/{queue_id}/retry", headers=headers)
    assert first.status_code == repeated.status_code == 409
    assert repeated.json()["details"]["idempotent_replay"] is True
    with Session(engine) as session:
        queue = session.get(models.RuntimeQueue, queue_id)
        request = session.get(models.RuntimeRequest, queued_response["runtime_request_id"])
        assert queue.status == request.status == "FAILED"
        assert request.error_code == "RUNTIME.QUEUE_RETRY_EXHAUSTED"


def test_maintenance_recovers_only_expired_initial_provision_lease(db_and_client):
    engine, client, _ = db_and_client
    old = datetime.utcnow() - timedelta(minutes=10)
    future = datetime.utcnow() + timedelta(minutes=5)
    with Session(engine) as session:
        for suffix, lease in (("expired", old), ("active", future)):
            session.add(models.RuntimeRequest(
                runtime_request_id=f"rrq_{suffix}", lab_release_id="release_rsa", lab_version_id="labv_rsa_v1",
                course_id="course_data_security", class_id="class_netsec_2301", student_id="student_2301001",
                mode="STUDENT", status="SCHEDULING", requested_by=f"user_{suffix}", idempotency_key=f"start-{suffix}",
                spec_snapshot_json=rsa_spec(), error_code=None, error_message=None,
                provision_owner=f"owner-{suffix}", provision_lease_expires_at=lease,
                submission_status="DRAFT", submitted_at=None, last_activity_at=old, created_at=old, updated_at=old,
            ))
        session.commit()

    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 0, "max_queue_attempts": 5}
    response = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "recover-initial-provision"}, json=body)
    assert response.status_code == 200
    assert len(response.json()["processing_recovered"]) == 1
    with Session(engine) as session:
        expired = session.get(models.RuntimeRequest, "rrq_expired")
        active = session.get(models.RuntimeRequest, "rrq_active")
        assert expired.status == "QUEUED" and expired.provision_owner is None
        assert active.status == "SCHEDULING" and active.provision_owner == "owner-active"
        assert session.scalar(select(func.count()).select_from(models.RuntimeQueue)) == 1


def test_independent_orphan_cleanup_does_not_change_active_group(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-orphan-task").json()
    stamp = datetime.utcnow()
    with Session(engine) as session:
        session.add(models.InfraNode(
            node_id="node_old", name="旧计算节点", agent_url="http://agent-old.test", status="READY",
            scheduling_paused=True, weight=1, labels_json={}, cpu_total=8, memory_total_mb=8192,
            last_seen_at=stamp, created_at=stamp,
        ))
        session.add(models.RuntimeCleanupTask(
            cleanup_task_id="rct_orphan", runtime_group_id=running["runtime_group_id"], node_id="node_old",
            provider_group_id="orphan-provider-group", provider_generation=1,
            intent="PROVISION_ORPHAN", status="WAITING",
            attempts=0, not_before=stamp - timedelta(seconds=1), processing_owner=None, lease_expires_at=None,
            error_code="RUNTIME.PROVISION_ROLLBACK_FAILED", error_message="测试孤儿资源", created_at=stamp, updated_at=stamp,
        ))
        session.commit()

    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    response = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "cleanup-independent-orphan"}, json=body)
    assert response.status_code == 200
    assert response.json()["expiry_results"] == [{
        "runtime_group_id": running["runtime_group_id"], "status": "ORPHAN_CLEANED", "cleanup_intent": "PROVISION_ORPHAN"
    }]
    with Session(engine) as session:
        assert session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).status == "RUNNING"
        assert session.get(models.RuntimeCleanupTask, "rct_orphan").status == "DONE"
    assert "orphan-provider-group" in fake.destroyed_group_ids


def test_stale_starting_cleanup_honors_queue_attempt_limit(db_and_client):
    engine, client, fake = db_and_client
    old = datetime.utcnow() - timedelta(minutes=10)
    future = datetime.utcnow() + timedelta(minutes=30)
    with Session(engine) as session:
        request = models.RuntimeRequest(
            runtime_request_id="rrq_stale_starting", lab_release_id="release_rsa", lab_version_id="labv_rsa_v1",
            course_id="course_data_security", class_id="class_netsec_2301", student_id="student_2301001",
            mode="STUDENT", status="STARTING", requested_by="user_stale_starting", idempotency_key="start-stale-starting",
            spec_snapshot_json=rsa_spec(), error_code=None, error_message=None,
            provision_owner="expired-provision", provision_lease_expires_at=old,
            submission_status="DRAFT", submitted_at=None, last_activity_at=old, created_at=old, updated_at=old,
        )
        session.add(request)
        session.add(models.RuntimeInstanceGroup(
            runtime_group_id="rtg_stale_starting", runtime_request_id=request.runtime_request_id,
            node_id="node_test", provider_group_id="rtg_stale_starting", status="STARTING",
            scheduler_score=100, scheduler_reason="测试崩溃恢复", scheduled_at=old, expires_at=future, destroyed_at=None,
            cleanup_attempts=0, cleanup_not_before=old, cleanup_intent="PROVISIONING",
            cleanup_owner="expired-provision", cleanup_lease_expires_at=old,
            cleanup_error_code=None, cleanup_error_message=None,
        ))
        session.add(models.RuntimeQueue(
            queue_id="rtq_stale_starting", runtime_request_id=request.runtime_request_id,
            status="WAITING", priority=100, attempts=5, not_before=None,
            processing_owner=None, lease_expires_at=None, enqueued_at=old,
        ))
        session.commit()

    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    response = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "cleanup-stale-starting-max"}, json=body)
    assert response.status_code == 200
    assert response.json()["expiry_results"] == [{
        "runtime_group_id": "rtg_stale_starting", "status": "FAILED", "cleanup_intent": "PROVISION_ROLLBACK"
    }]
    with Session(engine) as session:
        assert session.get(models.RuntimeRequest, "rrq_stale_starting").status == "FAILED"
        assert session.get(models.RuntimeQueue, "rtq_stale_starting").status == "FAILED"
        assert session.get(models.RuntimeInstanceGroup, "rtg_stale_starting").status == "FAILED"
    assert "rtg_stale_starting" in fake.destroyed_group_ids


def test_active_rebuild_lease_blocks_destroy_extend_and_rejudge(db_and_client):
    engine, client, _ = db_and_client
    running = start(client, "runtime-start-active-rebuild").json()
    instance_id = running["instance_ids"][0]
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        group.status = "STARTING"
        group.cleanup_intent = "REBUILD"
        group.cleanup_owner = "rebuild-active-owner"
        group.cleanup_lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
        session.commit()

    destroyed = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "并发销毁"})
    extended = client.post(f"/api/v1/runtime-instances/{instance_id}/extend", headers=STUDENT, json={"minutes": 10, "reason": "并发延时"})
    rejudged = client.post(f"/api/v1/runtime-instances/{instance_id}/rejudge", headers=STUDENT)
    assert destroyed.status_code == 409 and destroyed.json()["code"] == "RUNTIME.CLEANUP_IN_PROGRESS"
    assert extended.status_code == 409 and extended.json()["code"] == "RUNTIME.EXTEND_STATE_CONFLICT"
    assert rejudged.status_code == 409 and rejudged.json()["code"] == "RUNTIME.REJUDGE_STATE_CONFLICT"


def test_rebuild_restores_destroyed_group_and_clears_destroyed_at(db_and_client):
    engine, client, _ = db_and_client
    running = start(client, "runtime-start-rebuild-destroyed").json()
    instance_id = running["instance_ids"][0]
    destroyed = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "先销毁"})
    assert destroyed.status_code == 200 and destroyed.json()["status"] == "DESTROYED"
    rebuilt = client.post(f"/api/v1/runtime-instances/{instance_id}/rebuild", headers=STUDENT, json={"reason": "恢复环境"})
    assert rebuilt.status_code == 200 and rebuilt.json()["status"] == "RUNNING"
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        request = session.get(models.RuntimeRequest, running["runtime_request_id"])
        assert group.status == "RUNNING" and group.destroyed_at is None
        assert request.status == "RUNNING"
        assert all(item.status == "RUNNING" and item.ended_at is None for item in session.scalars(
            select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)
        ))


def test_rebuild_capture_start_failure_destroys_new_generation(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-rebuild-capture-failure").json()
    instance_id = running["instance_ids"][0]
    fake.capture_start_failures = 1
    rebuilt = client.post(f"/api/v1/runtime-instances/{instance_id}/rebuild", headers=STUDENT, json={"reason": "验证抓包失败回滚"})
    assert rebuilt.status_code == 503
    assert rebuilt.json()["code"] == "RUNTIME.CAPTURE_START_FAILED"
    assert any(group_id.endswith("-g2") for group_id in fake.destroyed_group_ids)
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        request = session.get(models.RuntimeRequest, running["runtime_request_id"])
        assert group.status == request.status == "FAILED"
        assert group.provider_group_id is None
        assert all(item.status == "FAILED" for item in session.scalars(
            select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)
        ))


def test_stale_rebuild_is_cleaned_and_marked_failed(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-stale-rebuild").json()
    old = datetime.utcnow() - timedelta(minutes=10)
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        group.status = "STARTING"
        group.cleanup_intent = "REBUILD"
        group.cleanup_owner = "expired-rebuild-owner"
        group.cleanup_lease_expires_at = old
        group.cleanup_not_before = old
        session.commit()

    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    response = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "cleanup-stale-rebuild"}, json=body)
    assert response.status_code == 200
    assert response.json()["expiry_results"] == [{
        "runtime_group_id": running["runtime_group_id"], "status": "FAILED", "cleanup_intent": "REBUILD"
    }]
    with Session(engine) as session:
        assert session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).status == "FAILED"
        assert session.get(models.RuntimeRequest, running["runtime_request_id"]).status == "FAILED"
        assert all(item.status == "FAILED" for item in session.scalars(
            select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == running["runtime_group_id"])
        ))
    assert running["runtime_group_id"] in fake.destroyed_group_ids


def test_rebuild_lease_loss_records_independent_orphan_cleanup(db_and_client):
    engine, client, fake = db_and_client
    running = start(client, "runtime-start-rebuild-lease-loss").json()
    instance_id = running["instance_ids"][0]

    def steal_rebuild_lease(_payload):
        with Session(engine) as session:
            group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
            group.cleanup_owner = "replacement-rebuild-owner"
            group.cleanup_lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
            session.commit()
        fake.destroy_failures = 1

    fake.create_hook = steal_rebuild_lease
    failed = client.post(f"/api/v1/runtime-instances/{instance_id}/rebuild", headers=STUDENT, json={"reason": "模拟租约切换"})
    assert failed.status_code == 409 and failed.json()["code"] == "RUNTIME.RECOVERY_LEASE_LOST"
    fake.create_hook = None
    with Session(engine) as session:
        task = session.scalar(select(models.RuntimeCleanupTask))
        assert task and task.intent == "REBUILD_ORPHAN" and task.status == "WAITING"
        task.not_before = datetime.utcnow() - timedelta(seconds=1)
        session.commit()

    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    fenced = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "fence-current-rebuild-orphan"}, json=body)
    assert fenced.status_code == 200
    assert fenced.json()["expiry_results"] == []
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        task = session.scalar(select(models.RuntimeCleanupTask))
        assert task.status == "WAITING"
        assert task.error_code == "RUNTIME.CLEANUP_FENCED_CURRENT_GENERATION"
        assert fake.destroyed_group_ids.count(task.provider_group_id) == 1
        group.status = "FAILED"
        group.provider_group_id = None
        group.cleanup_intent = None
        group.cleanup_owner = None
        group.cleanup_lease_expires_at = None
        group.cleanup_not_before = None
        request = session.get(models.RuntimeRequest, running["runtime_request_id"])
        request.status = "FAILED"
        task.not_before = datetime.utcnow() - timedelta(seconds=1)
        old_provider_group_id = task.provider_group_id
        session.commit()

    rebuilt = client.post(f"/api/v1/runtime-instances/{instance_id}/rebuild", headers=STUDENT, json={"reason": "新代接管"})
    assert rebuilt.status_code == 200 and rebuilt.json()["status"] == "RUNNING"
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        new_provider_group_id = group.provider_group_id
        assert group.provider_generation == 3
        assert new_provider_group_id != old_provider_group_id

    cleaned = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "cleanup-old-rebuild-orphan"}, json=body)
    assert cleaned.status_code == 200
    assert {item["cleanup_intent"] for item in cleaned.json()["expiry_results"]} == {"REBUILD_ORPHAN"}
    with Session(engine) as session:
        group = session.get(models.RuntimeInstanceGroup, running["runtime_group_id"])
        assert group.status == "RUNNING" and group.provider_group_id == new_provider_group_id
        assert session.scalar(select(models.RuntimeCleanupTask.status)) == "DONE"
    assert old_provider_group_id in fake.destroyed_group_ids
    assert new_provider_group_id not in fake.destroyed_group_ids


def test_destroy_rebuild_destroy_uses_distinct_lifecycle_event_keys(db_and_client):
    engine, client, _ = db_and_client
    running = start(client, "runtime-start-destroy-lifecycle").json()
    instance_id = running["instance_ids"][0]
    first = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "第一次销毁"})
    rebuilt = client.post(f"/api/v1/runtime-instances/{instance_id}/rebuild", headers=STUDENT, json={"reason": "重建"})
    second = client.post(f"/api/v1/runtime-instances/{instance_id}/destroy", headers=STUDENT, json={"reason": "第二次销毁"})
    assert first.status_code == rebuilt.status_code == second.status_code == 200
    with Session(engine) as session:
        events = list(session.scalars(select(DomainEventOutbox).where(
            DomainEventOutbox.event_type == "lab.instance.destroyed",
            DomainEventOutbox.aggregate_id == instance_id,
        )))
        assert {event.idempotency_key for event in events} == {
            f"lab.instance.destroyed:{running['runtime_group_id']}:g1",
            f"lab.instance.destroyed:{running['runtime_group_id']}:g2",
        }


def test_expire_rebuild_expire_uses_distinct_lifecycle_event_keys(db_and_client):
    engine, client, _ = db_and_client
    running = start(client, "runtime-start-expiry-lifecycle").json()
    instance_id = running["instance_ids"][0]
    body = {"node_timeout_seconds": 3600, "processing_timeout_seconds": 120, "retry_limit": 0, "expiry_limit": 5, "max_queue_attempts": 5}
    old = datetime.utcnow() - timedelta(minutes=1)
    with Session(engine) as session:
        session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).expires_at = old
        session.commit()
    first = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "expire-lifecycle-first"}, json=body)
    rebuilt = client.post(f"/api/v1/runtime-instances/{instance_id}/rebuild", headers=STUDENT, json={"reason": "到期后重建"})
    with Session(engine) as session:
        session.get(models.RuntimeInstanceGroup, running["runtime_group_id"]).expires_at = old
        session.commit()
    second = client.post("/api/v1/infrastructure/maintenance/run", headers={**ADMIN, "Idempotency-Key": "expire-lifecycle-second"}, json=body)
    assert first.status_code == rebuilt.status_code == second.status_code == 200
    assert first.json()["expiry_results"][0]["status"] == second.json()["expiry_results"][0]["status"] == "DESTROYED"
    with Session(engine) as session:
        events = list(session.scalars(select(DomainEventOutbox).where(
            DomainEventOutbox.event_type == "lab.instance.destroyed",
            DomainEventOutbox.aggregate_id == instance_id,
        )))
        assert {event.idempotency_key for event in events} == {
            f"lab.instance.destroyed:{running['runtime_group_id']}:g1",
            f"lab.instance.destroyed:{running['runtime_group_id']}:g2",
        }


@pytest.mark.parametrize("capacity", [
    capacity_facts(image_digests=[{}]),
    capacity_facts(cpu_available=float("nan")),
    capacity_facts(cpu_available=float("inf")),
    capacity_facts(running_groups=-1),
    capacity_facts(memory_available_mb=2_147_483_648, memory_total_mb=2_147_483_648),
    capacity_facts(running_groups=True),
], ids=["non-string-digest", "nan-cpu", "infinite-cpu", "negative-running", "oversized-memory", "boolean-running"])
def test_invalid_capacity_facts_are_skipped_and_request_is_queued(db_and_client, capacity):
    engine, client, fake = db_and_client
    fake.capacity_response = capacity
    response = start(client, f"runtime-start-invalid-capacity-{len(str(capacity))}")
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert response.json()["error"]["code"] == "RUNTIME.CAPACITY_UNAVAILABLE"
    with Session(engine) as session:
        request = session.get(models.RuntimeRequest, response.json()["runtime_request_id"])
        assert request.status == "QUEUED" and request.provision_owner is None
        assert session.scalar(select(func.count()).select_from(models.RuntimeInstanceGroup)) == 0


@pytest.mark.parametrize("flag", ["invalid_create_status", "duplicate_create_ids", "malformed_create_types"])
def test_invalid_create_facts_are_destroyed_before_failure(db_and_client, flag):
    engine, client, fake = db_and_client
    setattr(fake, flag, True)
    response = start(client, f"runtime-start-{flag}")
    assert response.status_code == 503
    assert response.json()["code"] == "RUNTIME.PROVIDER_RESPONSE_INVALID"
    with Session(engine) as session:
        group = session.scalar(select(models.RuntimeInstanceGroup))
        assert group.status == "FAILED" and group.provider_group_id is None
        assert session.scalar(select(func.count()).select_from(models.RuntimeCleanupTask)) == 0
    assert fake.destroyed_group_ids == [group.runtime_group_id]


def test_overlong_recovery_target_is_rejected_before_action_creation(db_and_client):
    engine, client, _ = db_and_client
    overlong = "x" * 37
    heartbeat = client.post(
        f"/api/v1/infrastructure/nodes/{overlong}/heartbeat",
        headers={**ADMIN, "Idempotency-Key": "overlong-heartbeat"},
    )
    retry = client.post(
        f"/api/v1/infrastructure/queue/{overlong}/retry",
        headers={**ADMIN, "Idempotency-Key": "overlong-queue-retry"},
    )
    assert heartbeat.status_code == retry.status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(models.RuntimeAdminAction)) == 0
