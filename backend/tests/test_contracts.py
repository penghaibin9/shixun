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
    assert "/api/v1/auth/users" in contract["paths"]
    assert "/api/v1/auth/reconciliation/scan" in contract["paths"]
    assert "/api/v1/classes/{class_id}/roster/freeze" in contract["paths"]
    assert "/api/v1/integration/outbox/dispatch" in contract["paths"]
    assert "Error" in contract["components"]["schemas"]


def test_frozen_openapi_never_leaves_a_json_success_response_as_an_empty_schema():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    assert "ApiObjectResponse" not in contract["components"]["schemas"]
    for path, operations in contract["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for status in ("200", "201", "202"):
                response = operation.get("responses", {}).get(status)
                content = response.get("content", {}) if response else {}
                schema = content.get("application/json", {}).get("schema")
                if schema is not None:
                    assert schema != {}, f"{method.upper()} {path} 的 {status} JSON 响应没有冻结类型"
                    references = schema.get("anyOf") if isinstance(schema, dict) else None
                    assert "$ref" in schema or (
                        isinstance(references, list) and references and all("$ref" in item for item in references)
                    ), f"{method.upper()} {path} 的 {status} JSON 响应必须引用具名模型"


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


def test_grade_event_provenance_is_frozen_in_database_and_openapi_contracts():
    ownership = json.loads((ROOT / "docs/contracts/database-ownership-v1.json").read_text(encoding="utf-8"))
    provenance = ownership["authority_contracts"]["grading_source_provenance"]
    assert provenance["owner"] == "F"
    assert provenance["table"] == "grade_event"
    assert provenance["proof_fact_table"] == "grade_score_proof"
    assert provenance["proof_producer_actor_user_id"] == "service_teaching_score_prover"
    assert provenance["verified_statuses"] == ["VERIFIED_OUTBOX", "VERIFIED_SCORE_PROOF"]
    assert provenance["legacy_status"] == "QUARANTINED_LEGACY"
    table = Base.metadata.tables["grade_event"]
    assert {"source_verification_status", "source_proof_issuer", "source_proof_digest"} <= set(table.columns.keys())
    assert "ix_grade_event_verification_scope" in {index.name for index in table.indexes}
    proof_table = Base.metadata.tables["grade_score_proof"]
    assert {"source_proof_event_id", "score_event_id", "score_payload_sha256"} <= set(proof_table.columns.keys())
    assert "ix_grade_score_proof_scope" in {index.name for index in proof_table.indexes}
    openapi = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    description = openapi["components"]["schemas"]["EventEnvelope"]["properties"]["payload"]["description"]
    assert "score_proof_event_id" in description and "grading.score.proof.frozen" in description
    assert "service_teaching_score_prover" in description


def test_teaching_score_proof_and_request_boundaries_are_frozen():
    ownership = json.loads((ROOT / "docs/contracts/database-ownership-v1.json").read_text(encoding="utf-8"))
    provenance = ownership["authority_contracts"]["teaching_score_provenance"]
    assert provenance["owner"] == "A"
    assert provenance["table"] == "teaching_score_proof"
    assert provenance["proof_event_type"] == "grading.score.proof.frozen"
    assert provenance["proof_producer_actor_user_id"] == "service_teaching_score_prover"

    proof_table = Base.metadata.tables["teaching_score_proof"]
    assert {
        "source_fact_id", "score_event_id", "score_proof_event_id",
        "frozen_question_evidence_json", "answer_evidence_json", "scoring_evidence_json",
        "score_payload_sha256",
    } <= set(proof_table.columns.keys())
    assert "ix_teaching_score_proof_scope" in {index.name for index in proof_table.indexes}
    assert Base.metadata.tables["assignment_question_ref"].columns["question_version"].type.length == 64
    assert Base.metadata.tables["quiz_question_ref"].columns["question_version"].type.length == 64

    openapi = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    schemas = openapi["components"]["schemas"]
    question_ref = schemas["QuestionRefIn"]
    assert question_ref["additionalProperties"] is False
    assert set(question_ref["properties"]) == {"question_id"}
    for schema_name in ("AssignmentCreate", "QuizCreate", "SubmissionIn", "QuizSubmitIn"):
        assert schemas[schema_name]["additionalProperties"] is False
    assert set(schemas["SubmissionIn"]["properties"]) == {"answers"}
    assert set(schemas["QuizSubmitIn"]["properties"]) == {"answers"}


def test_student_task_reads_are_typed_and_never_expose_frozen_scoring_evidence():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    expected = {
        "/api/v1/assignments/my": "StudentAssignmentListResponse",
        "/api/v1/assignments/{assignment_id}/student-task": "StudentAssignmentTaskResponse",
        "/api/v1/quizzes/my": "StudentQuizListResponse",
        "/api/v1/quizzes/{quiz_id}/student-task": "StudentQuizTaskResponse",
    }
    for path, response_schema in expected.items():
        response = contract["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert response["$ref"].endswith(f"/{response_schema}")

    question = contract["components"]["schemas"]["StudentTaskQuestionResponse"]
    assert set(question["properties"]) == {"question_ref_id", "question_id", "question_type", "stem", "options"}
    assert {"answer", "question_snapshot", "question_version", "max_score"}.isdisjoint(question["properties"])
    options = contract["components"]["schemas"]["StudentTaskOptionResponse"]
    assert set(options["properties"]) == {"key", "text"}


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


def test_openapi_does_not_publish_development_identity_headers():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    header_names = {
        parameter["name"].lower()
        for operations in contract["paths"].values()
        for operation in operations.values()
        if isinstance(operation, dict)
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header"
    }
    assert {"x-user-id", "x-role", "x-teacher-id", "x-student-id", "x-permissions", "x-course-ids", "x-class-ids"}.isdisjoint(header_names)
