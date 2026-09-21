import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.labs import models
from app.labs.database import get_session
from app.main import app

pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要真实 MySQL 8.4 的 YUEKE_DATABASE_URL")

HEADERS = {
    "X-User-Id": "user_test_c",
    "X-Role": "teacher",
    "X-Teacher-Id": "teacher_test_c",
    "X-Permissions": "labs.read,labs.write,labs.publish,labs.knowledge.write",
    "X-Course-Ids": "course_data_security",
    "X-Class-Ids": "class_netsec_2301",
}


@pytest.fixture()
def client():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def test_rsa_is_persisted_in_mysql_with_normalized_topology():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    with Session(engine) as session:
        definition = session.get(models.LabDefinition, "lab_rsa")
        version = session.scalar(select(models.LabVersion).where(models.LabVersion.lab_definition_id == "lab_rsa", models.LabVersion.version == 1))
        assert definition and version and version.status == "PUBLISHED"
        assert session.scalar(select(func.count()).select_from(models.LabSceneNode)) >= 2
        assert session.scalar(select(func.count()).select_from(models.LabCheckpoint).where(models.LabCheckpoint.lab_version_id == version.lab_version_id)) == 5
    engine.dispose()


def test_api_export_and_published_version_immutability(client: TestClient):
    listing = client.get("/api/v1/labs", headers=HEADERS)
    assert listing.status_code == 200
    rsa = next(item for item in listing.json()["items"] if item["lab_definition_id"] == "lab_rsa")
    version_id = rsa["latest_version"]["lab_version_id"]
    exported = client.get(f"/api/v1/lab-versions/{version_id}/export.json", headers=HEADERS)
    assert exported.status_code == 200
    assert exported.json()["total_score"] == 100
    immutable = client.patch(f"/api/v1/lab-versions/{version_id}", headers={**HEADERS, "X-Idempotency-Key": "test-immutable-v1"}, json={"spec": exported.json()})
    assert immutable.status_code == 409
    assert immutable.json()["code"] == "LAB.VERSION_IMMUTABLE"


def test_class_scope_and_runtime_provider_unavailable_are_explicit(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("YUEKE_RUNTIME_PROVIDER_URL", raising=False)
    rsa = next(item for item in client.get("/api/v1/labs", headers=HEADERS).json()["items"] if item["lab_definition_id"] == "lab_rsa")
    version_id = rsa["latest_version"]["lab_version_id"]
    payload = {
        "lab_version_id": version_id,
        "course_id": "course_data_security",
        "class_id": "class_forbidden",
        "lesson_id": "lesson_03_04",
        "opens_at": datetime.now().isoformat(),
        "closes_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        "max_attempts": 3,
        "timeout_minutes": 60,
        "max_concurrency": 43,
        "teacher_preview_required": True,
    }
    denied = client.post("/api/v1/lab-releases", headers={**HEADERS, "X-Idempotency-Key": "test-denied-class-v1"}, json=payload)
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH.CLASS_SCOPE_DENIED"

    payload["class_id"] = "class_netsec_2301"
    key = f"test-release-{datetime.now().timestamp()}"
    created = client.post("/api/v1/lab-releases", headers={**HEADERS, "X-Idempotency-Key": key}, json=payload)
    assert created.status_code == 201
    release_id = created.json()["lab_release_id"]
    repeated = client.post("/api/v1/lab-releases", headers={**HEADERS, "X-Idempotency-Key": key}, json=payload)
    assert repeated.status_code == 201
    assert repeated.json()["lab_release_id"] == release_id
    assert client.post(f"/api/v1/lab-releases/{release_id}/preflight", headers={**HEADERS, "X-Idempotency-Key": f"{key}-preflight"}).json()["passed"] is True
    preview = client.post(f"/api/v1/lab-releases/{release_id}/teacher-preview", headers={**HEADERS, "X-Idempotency-Key": f"{key}-preview"})
    assert preview.status_code == 503
    assert preview.json()["code"] == "LAB.RUNTIME_PROVIDER_UNAVAILABLE"


def test_knowledge_question_mapping_is_persisted(client: TestClient):
    key = f"test-knowledge-{datetime.now().timestamp()}"
    payload = {"course_id": "course_data_security", "title": "RSA 密钥对与数字签名", "explain_text": "先计算摘要，再用私钥签名并由公钥验签。", "question_ids": ["question_rsa_006"], "diagrams": [{"file_id": "file_rsa_diagram", "title": "RSA 数字签名流程", "order_no": 1}]}
    created = client.post("/api/v1/lab-knowledge", headers={**HEADERS, "X-Idempotency-Key": key}, json=payload)
    assert created.status_code == 201
    assert created.json()["question_ids"] == ["question_rsa_006"]
    listed = client.get("/api/v1/lab-knowledge", headers=HEADERS)
    assert any(item["knowledge_point_id"] == created.json()["knowledge_point_id"] for item in listed.json()["items"])


def test_seeded_explain_diagram_download_requires_context(client: TestClient):
    path = "/api/v1/lab-knowledge/kp_rsa_signature/diagrams/diag_rsa_signature/download"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"RSA" in response.content
