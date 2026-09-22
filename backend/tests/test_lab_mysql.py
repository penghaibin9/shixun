import json
import os
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.labs import models
from app.labs.database import get_session
from app.labs.seed import seed_formal_lab_definitions, seed_rsa
from app.main import app
from app.resources.models import LessonResource, Question, QuestionBank, QuestionLessonMap
from app.teaching.models import ClassCourse, TeachingClass, TeachingTeacherAssignment

pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要真实 MySQL 8.4 的 YUEKE_DATABASE_URL")

HEADERS = {
    "X-User-Id": "user_test_c",
    "X-Role": "teacher",
    "X-Teacher-Id": "teacher_test_c",
    "X-Permissions": "labs.read,labs.write,labs.publish,labs.knowledge.write",
    "X-Course-Ids": "course_data_security",
    "X-Class-Ids": "class_netsec_2301",
}


@pytest.fixture(scope="module", autouse=True)
def rsa_baseline():
    """真实空库测试必须显式验证幂等的 RSA 基线初始化。"""
    if os.getenv("YUEKE_DATABASE_URL"):
        seed_rsa()
        engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
        with Session(engine) as session:
            if not session.get(TeachingClass, "class_netsec_2301"):
                session.add(TeachingClass(class_id="class_netsec_2301", name="网络安全 2301 班", term="2026 秋季", owner_teacher_id="teacher_test_c", created_at=datetime.now()))
                session.flush()
            if not session.scalar(select(ClassCourse).where(ClassCourse.class_id == "class_netsec_2301", ClassCourse.course_id == "course_data_security")):
                session.add(ClassCourse(class_course_id="cc_netsec_2301_data_security", class_id="class_netsec_2301", course_id="course_data_security"))
            if not session.scalar(select(TeachingTeacherAssignment).where(TeachingTeacherAssignment.teacher_id == "teacher_test_c", TeachingTeacherAssignment.class_id == "class_netsec_2301", TeachingTeacherAssignment.course_id == "course_data_security")):
                session.add(TeachingTeacherAssignment(assignment_id="tta_test_c_netsec_2301", teacher_id="teacher_test_c", class_id="class_netsec_2301", course_id="course_data_security"))
            session.commit()
        engine.dispose()


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
        assert session.scalar(select(func.count()).select_from(models.LabDefinition).where(models.LabDefinition.course_id == "course_data_security")) == 12
        assert session.scalar(select(func.count()).select_from(models.LabVersion).where(models.LabVersion.status == "PUBLISHED")) >= 12
        links = list(session.scalars(select(LessonResource.linked_lab_definition_id).where(LessonResource.course_id == "course_data_security", LessonResource.lesson_id.like("lesson_lab_%"))))
        assert len(links) == 12 and all(links) and len(set(links)) == 12
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


def test_exported_json_can_be_imported_as_a_new_validated_draft(client: TestClient):
    rsa = next(item for item in client.get("/api/v1/labs", headers=HEADERS).json()["items"] if item["lab_definition_id"] == "lab_rsa")
    exported = client.get(f"/api/v1/lab-versions/{rsa['latest_version']['lab_version_id']}/export.json", headers=HEADERS)
    assert exported.status_code == 200
    payload = exported.json()
    suffix = str(int(datetime.now().timestamp() * 1_000_000))[-10:]
    payload["lab_definition_id"] = f"lab_import_{suffix}"
    payload["name"] = f"实验定义导入回环 {suffix}"
    for index, checkpoint in enumerate(payload["checkpoints"], start=1):
        checkpoint["checkpoint_id"] = f"cp_imp_{suffix}_{index}"
    imported = client.post(
        "/api/v1/labs/import",
        headers={**HEADERS, "X-Idempotency-Key": f"test-lab-import-{suffix}"},
        data={
            "course_id": "course_data_security",
            "code": f"IMP-{suffix}",
            "category": "导入验证",
            "objective": "验证导出的实验定义可重新导入并保持结构一致。",
        },
        files={"file": ("lab.json", json.dumps(payload, ensure_ascii=False).encode(), "application/json")},
    )
    assert imported.status_code == 201, imported.text
    version = imported.json()["latest_version"]
    assert version["status"] == "DRAFT"
    roundtrip = client.get(f"/api/v1/lab-versions/{version['lab_version_id']}/export.json", headers=HEADERS)
    assert roundtrip.status_code == 200
    assert roundtrip.json() == payload


def test_import_rejects_unknown_top_level_and_nested_fields(client: TestClient):
    rsa = next(item for item in client.get("/api/v1/labs", headers=HEADERS).json()["items"] if item["lab_definition_id"] == "lab_rsa")
    exported = client.get(f"/api/v1/lab-versions/{rsa['latest_version']['lab_version_id']}/export.json", headers=HEADERS).json()
    for label, payload in (
        ("top", {**exported, "unknown_field": True}),
        ("nested", {**exported, "runtime_policy": {**exported["runtime_policy"], "unknown_field": True}}),
    ):
        candidate = deepcopy(payload)
        suffix = str(int(datetime.now().timestamp() * 1_000_000))[-10:]
        candidate["lab_definition_id"] = f"lab_bad_{label}_{suffix}"[:36]
        response = client.post(
            "/api/v1/labs/import",
            headers={**HEADERS, "X-Idempotency-Key": f"test-lab-strict-{label}-{suffix}"},
            data={"course_id": "course_data_security", "code": f"BAD-{label}-{suffix}", "category": "校验", "objective": "未知字段必须被拒绝。"},
            files={"file": ("lab.json", json.dumps(candidate, ensure_ascii=False).encode(), "application/json")},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "LAB.IMPORT_SCHEMA_INVALID"


def test_formal_seed_ignores_later_user_draft_version(client: TestClient):
    rsa = next(item for item in client.get("/api/v1/labs", headers=HEADERS).json()["items"] if item["lab_definition_id"] == "lab_rsa")
    frozen_v1_id = rsa["latest_version"]["lab_version_id"]
    key = f"test-seed-with-draft-{datetime.now().timestamp()}"
    cloned = client.post("/api/v1/labs/lab_rsa/versions", headers={**HEADERS, "X-Idempotency-Key": key}, json={})
    assert cloned.status_code == 201, cloned.text
    draft_id = cloned.json()["lab_version_id"]
    assert cloned.json()["version"] >= 2 and cloned.json()["status"] == "DRAFT"
    try:
        result = seed_formal_lab_definitions()
        assert result == {"definitions": 12, "created": 0, "linked": 0}
        engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
        with Session(engine) as session:
            frozen_v1 = session.get(models.LabVersion, frozen_v1_id)
            draft = session.get(models.LabVersion, draft_id)
            assert frozen_v1 and frozen_v1.version == 1 and frozen_v1.status == "PUBLISHED"
            assert draft and draft.status == "DRAFT"
        engine.dispose()
    finally:
        engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
        with Session(engine) as session:
            session.execute(delete(models.LabVersion).where(models.LabVersion.lab_version_id == draft_id))
            session.commit()
        engine.dispose()


def test_class_scope_and_runtime_provider_unavailable_are_explicit(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("YUEKE_RUNTIME_PROVIDER_URL", raising=False)
    rsa = next(item for item in client.get("/api/v1/labs", headers=HEADERS).json()["items"] if item["lab_definition_id"] == "lab_rsa")
    version_id = rsa["latest_version"]["lab_version_id"]
    payload = {
        "lab_version_id": version_id,
        "course_id": "course_data_security",
        "class_id": "class_forbidden",
        "lesson_id": "lesson_lab_03",
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
    missing_lesson = dict(payload)
    missing_lesson.pop("lesson_id")
    denied_missing_lesson = client.post("/api/v1/lab-releases", headers={**HEADERS, "X-Idempotency-Key": "test-release-missing-lesson"}, json=missing_lesson)
    assert denied_missing_lesson.status_code == 422

    wrong_mapping = {**payload, "lesson_id": "lesson_lab_04"}
    denied_wrong_mapping = client.post("/api/v1/lab-releases", headers={**HEADERS, "X-Idempotency-Key": "test-release-wrong-lesson"}, json=wrong_mapping)
    assert denied_wrong_mapping.status_code == 422
    assert denied_wrong_mapping.json()["code"] == "LAB.RELEASE_LESSON_MISMATCH"

    unassigned_headers = {**HEADERS, "X-User-Id": "user_other_teacher", "X-Teacher-Id": "teacher_other"}
    denied_assignment = client.post("/api/v1/lab-releases", headers={**unassigned_headers, "X-Idempotency-Key": "test-release-unassigned-teacher"}, json=payload)
    assert denied_assignment.status_code == 403
    assert denied_assignment.json()["code"] == "AUTH.TEACHER_ASSIGNMENT_DENIED"

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
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    question_id = f"question_lab_c_{datetime.now().timestamp()}".replace(".", "")[:36]
    bank_created = False
    with Session(engine) as session:
        bank = session.scalar(select(QuestionBank).where(QuestionBank.course_id == "course_data_security"))
        if not bank:
            bank = QuestionBank(question_bank_id="qb_lab_c_mapping", course_id="course_data_security", name="实验知识点映射题库", status="PUBLISHED", created_by="user_test_c", created_at=datetime.now())
            session.add(bank)
            session.flush()
            bank_created = True
        session.add(Question(question_id=question_id, question_bank_id=bank.question_bank_id, import_job_id=None, source_row_number=None, question_type="TRUE_FALSE", stem="RSA 签名应使用私钥生成。", answer_json={"value": True}, status="APPROVED", created_by="user_test_c", created_at=datetime.now(), submitted_at=datetime.now(), reviewed_by="reviewer_test_c", reviewed_at=datetime.now()))
        session.add(QuestionLessonMap(question_lesson_map_id=f"qlm_{question_id}"[:36], question_id=question_id, lesson_id="lesson_lab_04"))
        session.commit()
    knowledge_id = None
    try:
        key = f"test-knowledge-{datetime.now().timestamp()}"
        payload = {"course_id": "course_data_security", "title": "RSA 密钥对与数字签名", "explain_text": "先计算摘要，再用私钥签名并由公钥验签。", "question_ids": [question_id], "diagrams": [{"file_id": "file_rsa_diagram", "title": "RSA 数字签名流程", "order_no": 1}]}
        created = client.post("/api/v1/lab-knowledge", headers={**HEADERS, "X-Idempotency-Key": key}, json=payload)
        assert created.status_code == 201
        knowledge_id = created.json()["knowledge_point_id"]
        assert created.json()["question_ids"] == [question_id]
        listed = client.get("/api/v1/lab-knowledge", headers=HEADERS)
        assert any(item["knowledge_point_id"] == knowledge_id for item in listed.json()["items"])
    finally:
        with Session(engine) as session:
            if knowledge_id:
                session.execute(delete(models.LabQuestionKnowledgeMap).where(models.LabQuestionKnowledgeMap.knowledge_point_id == knowledge_id))
                session.execute(delete(models.LabExplainDiagram).where(models.LabExplainDiagram.knowledge_point_id == knowledge_id))
                session.execute(delete(models.LabKnowledgePoint).where(models.LabKnowledgePoint.knowledge_point_id == knowledge_id))
            session.execute(delete(QuestionLessonMap).where(QuestionLessonMap.question_id == question_id))
            session.execute(delete(Question).where(Question.question_id == question_id))
            if bank_created:
                session.execute(delete(QuestionBank).where(QuestionBank.question_bank_id == "qb_lab_c_mapping"))
            session.commit()
        engine.dispose()


def test_seeded_explain_diagram_download_requires_context(client: TestClient):
    path = "/api/v1/lab-knowledge/kp_rsa_signature/diagrams/diag_rsa_signature/download"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"RSA" in response.content
