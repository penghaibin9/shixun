import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.common.models import Base
from app.grading import models as grading_models  # noqa: F401
from app.lab_classroom import models as classroom_models  # noqa: F401
from app.labs import models as lab_models  # noqa: F401
from app.resources import models as resource_models  # noqa: F401
from app.runtime import models as runtime_models  # noqa: F401
from app.teaching import models as teaching_models  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_openapi_is_valid_and_has_v1_contracts():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    assert contract["openapi"].startswith("3.1")
    assert "/api/v1/auth/context" in contract["paths"]
    assert "/api/v1/classes/{class_id}/roster/freeze" in contract["paths"]
    assert "/api/v1/integration/outbox/dispatch" in contract["paths"]
    assert "Error" in contract["components"]["schemas"]


def test_frozen_openapi_exactly_matches_application():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    assert contract == app.openapi()


def test_question_import_contract_requires_bounded_idempotency_and_binary_xlsx():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    operation = contract["paths"]["/api/v1/questions/import"]["post"]
    idempotency = next(item for item in operation["parameters"] if item["name"] == "Idempotency-Key")
    assert idempotency["required"] is True
    assert idempotency["schema"]["maxLength"] == 128

    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    for path in (
        "/api/v1/questions/import-template.xlsx",
        "/api/v1/questions/import-jobs/{job_id}/error-rows.xlsx",
    ):
        content = contract["paths"][path]["get"]["responses"]["200"]["content"]
        assert content[media_type]["schema"] == {"type": "string", "format": "binary"}


def test_runtime_recovery_contract_is_typed_and_requires_idempotency():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    expected = {
        "/api/v1/infrastructure/nodes/{node_id}/heartbeat": "RuntimeHeartbeatResult",
        "/api/v1/infrastructure/queue/{queue_id}/retry": "RuntimeQueueRetryResult",
        "/api/v1/infrastructure/maintenance/run": "RuntimeMaintenanceResult",
    }
    for path, response_schema in expected.items():
        operation = contract["paths"][path]["post"]
        idempotency = next(item for item in operation["parameters"] if item["name"] == "Idempotency-Key")
        assert idempotency["required"] is True
        assert idempotency["schema"]["minLength"] == 8
        assert idempotency["schema"]["maxLength"] == 255
        response = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert response["$ref"].endswith(f"/{response_schema}")
    maintenance_body = contract["paths"]["/api/v1/infrastructure/maintenance/run"]["post"]["requestBody"]
    assert maintenance_body["required"] is True
    assert maintenance_body["content"]["application/json"]["schema"]["$ref"].endswith("/RuntimeMaintenanceRun")


def test_artifact_storage_contract_exposes_real_zip_and_typed_bundle_request():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    download = contract["paths"]["/api/v1/artifact-storage/bundles/{assignment_id}"]["get"]
    capability = next(item for item in download["parameters"] if item["name"] == "capability")
    assert capability["required"] is True
    assert capability["schema"]["minLength"] == 40
    assert capability["schema"]["maxLength"] == 32768
    assert download["responses"]["200"]["content"] == {
        "application/zip": {"schema": {"type": "string", "format": "binary"}}
    }
    bundle_body = contract["paths"]["/api/v1/runtime/log-artifacts/bundle-url"]["post"]["requestBody"]
    assert bundle_body["content"]["application/json"]["schema"]["$ref"].endswith("/ArtifactBundleRequest")


def test_database_tables_have_exactly_one_frozen_owner():
    contract = json.loads((ROOT / "docs/contracts/database-ownership-v1.json").read_text(encoding="utf-8"))
    claimed = [table for tables in contract["owners"].values() for table in tables]
    assert len(claimed) == len(set(claimed))
    assert set(claimed) == set(Base.metadata.tables)


def test_lesson_resource_is_only_a_resource_extension_of_a_curriculum():
    columns = set(Base.metadata.tables["lesson_resource"].columns.keys())
    assert {"course_id", "lesson_id", "purpose", "environment", "principle", "steps_summary"} <= columns
    assert {"lesson_kind", "chapter_no", "lesson_code", "title"}.isdisjoint(columns)


def test_context_requires_identity_and_returns_frozen_shape():
    client = TestClient(app)
    assert client.get("/api/v1/auth/context").json()["code"] == "AUTH.UNAUTHENTICATED"
    response = client.get("/api/v1/auth/context", headers={"X-User-Id": "usr_1", "X-Role": "teacher", "X-Course-Ids": "course_1", "X-Class-Ids": "class_1"})
    assert response.status_code == 200
    assert response.json()["course_ids"] == ["course_1"]
    assert response.headers["X-Request-Id"].startswith("req_")


def test_production_rejects_development_identity_headers(monkeypatch):
    monkeypatch.setenv("YUEKE_ENV", "production")
    client = TestClient(app)
    response = client.get("/api/v1/auth/context", headers={"X-User-Id": "spoofed", "X-Role": "admin", "X-Permissions": "audit:read"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH.TRUSTED_IDENTITY_REQUIRED"
