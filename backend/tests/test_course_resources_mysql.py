import os
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox, FileObject
from app.common.context import UserContext
from app.main import app
from app.resources.catalog import COURSE_ID
from app.resources.models import Question, QuestionBank, QuestionExplanation, QuestionLessonMap, QuestionOption, Resource, ResourceDeliveryManifest, ResourceVersion, VideoAsset
from app.resources.service import ResourceService

pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL 集成库")

HEADERS = {
    "X-User-Id": "teacher_b",
    "X-Role": "teacher",
    "X-Teacher-Id": "teacher_b",
    "X-Course-Ids": COURSE_ID,
    "X-Permissions": "resources:read,resources:write,resources:review,resources:freeze",
}
REVIEW_HEADERS = {**HEADERS, "X-User-Id": "reviewer_b", "X-Teacher-Id": "reviewer_b"}


@pytest.fixture()
def client():
    return TestClient(app)


def test_mysql_catalog_audit_manifest_and_freeze_blocker(client):
    theory = client.get("/api/v1/resources/theory-lessons", headers=HEADERS).json()
    labs = client.get("/api/v1/resources/lab-lessons", headers=HEADERS).json()
    assert theory["total"] == 37
    assert labs["total"] == 12
    assert all(row["purpose"] and row["environment"] and row["principle"] for row in labs["items"])
    audit = client.post("/api/v1/resources/audit/run", headers=HEADERS, json={"course_id": COURSE_ID})
    assert audit.status_code == 200
    assert audit.json()["total"] == 196
    assert audit.json()["blocking"] > 0
    manifest = client.get("/api/v1/resources/delivery/manifest.json", headers=HEADERS).json()
    assert manifest["status"] == "BLOCKED"
    assert manifest["theory_lessons"] == 37 and manifest["lab_lessons"] == 12
    xlsx = client.get("/api/v1/resources/delivery/manifest.xlsx", headers=HEADERS)
    assert xlsx.status_code == 200 and xlsx.content.startswith(b"PK")
    frozen = client.post("/api/v1/resources/delivery/freeze", headers=HEADERS, json={"course_id": COURSE_ID})
    assert frozen.status_code == 409
    assert frozen.json()["code"] == "RESOURCE.DELIVERY_BLOCKED"


def test_three_dimension_filter_sha_duration_and_frozen_immutability(client, tmp_path):
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    suffix = uuid4().hex[:8]
    created_ids = []
    file_id = f"file_{suffix}"
    sha = "a" * 64
    video_path = tmp_path / f"video-{suffix}.mp4"
    video_path.write_bytes(b"not-a-real-video")
    with Session(engine) as session:
        session.add(FileObject(file_id=file_id, storage_provider="local", bucket="tests", object_key=str(video_path), original_name="真实解析样例.mp4", mime_type="video/mp4", size_bytes=123, sha256=sha, created_by="teacher_b", created_at=datetime.utcnow()))
        session.commit()
    try:
        for name, resource_type in [(f"RSA 视频 {suffix}", "VIDEO"), (f"RSA 讲义 {suffix}", "PPT")]:
            response = client.post("/api/v1/resources", headers=HEADERS, json={"course_id": COURSE_ID, "lesson_id": "lesson_theory_3_2", "name": name, "resource_type": resource_type})
            assert response.status_code == 201
            created_ids.append(response.json()["resource_id"])
        filtered = client.get("/api/v1/resources", headers=HEADERS, params={"course_id": COURSE_ID, "status": "DRAFT", "name": suffix, "resource_type": "VIDEO"}).json()
        assert filtered["total"] == 1 and filtered["items"][0]["resource_type"] == "VIDEO"
        video_id = filtered["items"][0]["resource_id"]
        bad_sha = client.post(f"/api/v1/resources/{video_id}/versions", headers=HEADERS, json={"file_id": file_id, "sha256": "b" * 64})
        assert bad_sha.status_code == 422 and bad_sha.json()["code"] == "RESOURCE.FILE_SHA256_MISMATCH"
        probe = client.post(f"/api/v1/resources/{video_id}/versions", headers=HEADERS, json={"file_id": file_id, "sha256": sha})
        assert probe.status_code in {422, 503}
        assert probe.json()["code"] in {"RESOURCE.MEDIA_PROBE_UNAVAILABLE", "RESOURCE.VIDEO_PROBE_FAILED"}
        with Session(engine) as session:
            resource = session.get(Resource, video_id); resource.status = "FROZEN"; session.commit()
        immutable = client.post(f"/api/v1/resources/{video_id}/versions", headers=HEADERS, json={"file_id": file_id, "sha256": sha})
        assert immutable.status_code == 409 and immutable.json()["code"] == "RESOURCE.VERSION_FROZEN"
    finally:
        with Session(engine) as session:
            for resource_id in created_ids:
                versions = list(session.scalars(select(ResourceVersion).where(ResourceVersion.resource_id == resource_id)))
                for item in versions:
                    session.execute(delete(VideoAsset).where(VideoAsset.resource_version_id == item.resource_version_id))
                session.execute(delete(ResourceVersion).where(ResourceVersion.resource_id == resource_id))
                session.execute(delete(Resource).where(Resource.resource_id == resource_id))
            session.execute(delete(FileObject).where(FileObject.file_id == file_id))
            session.commit()


def test_question_coverage_requires_four_published_types(client):
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    lesson_id = "lesson_theory_3_2"
    question_ids = []
    try:
        for question_type in ["FILL", "SINGLE", "MULTIPLE", "TRUE_FALSE"]:
            response = client.post("/api/v1/questions", headers=HEADERS, json={"course_id": COURSE_ID, "lesson_id": lesson_id, "question_type": question_type, "stem": f"{question_type} 测试题", "answer": ["A"], "explanation": "用于验证覆盖门禁", "options": [{"key": "A", "text": "正确答案", "is_correct": True}]})
            assert response.status_code == 201
            question_id = response.json()["question_id"]; question_ids.append(question_id)
            reviewed = client.post(f"/api/v1/questions/{question_id}/review", headers=REVIEW_HEADERS)
            assert reviewed.status_code == 200
        coverage = client.get("/api/v1/questions/coverage", headers=HEADERS).json()
        item = next(row for row in coverage["items"] if row["lesson_id"] == lesson_id)
        assert item["passed"] is True
        assert set(item["types"]) == {"FILL", "SINGLE", "MULTIPLE", "TRUE_FALSE"}
    finally:
        with Session(engine) as session:
            session.execute(delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids)))
            session.execute(delete(QuestionExplanation).where(QuestionExplanation.question_id.in_(question_ids)))
            session.execute(delete(QuestionLessonMap).where(QuestionLessonMap.question_id.in_(question_ids)))
            session.execute(delete(Question).where(Question.question_id.in_(question_ids)))
            remaining = session.scalar(select(Question).where(Question.question_bank_id == f"qb_{COURSE_ID}").limit(1))
            if not remaining: session.execute(delete(QuestionBank).where(QuestionBank.question_bank_id == f"qb_{COURSE_ID}"))
            session.commit()


def test_freeze_pass_creates_manifest_when_dynamic_audit_has_no_blockers(monkeypatch):
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    context = UserContext("reviewer_b", "teacher", "reviewer_b", None, frozenset({"resources:read", "resources:freeze"}), frozenset({COURSE_ID}), frozenset())
    with Session(engine) as session:
        session.execute(delete(ResourceDeliveryManifest).where(ResourceDeliveryManifest.course_id == COURSE_ID))
        session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.event_type == "resource.delivery.frozen", DomainEventOutbox.aggregate_id == COURSE_ID))
        session.commit()
        svc = ResourceService(session, context)
        clean = {"course_id": COURSE_ID, "total": 196, "pass": 196, "warning": 0, "blocking": 0, "blocking_items": [], "procurement_mapping": svc.procurement_mapping(), "checked_at": datetime.utcnow().isoformat() + "Z"}
        monkeypatch.setattr(svc, "audit", lambda course_id, persist=False: clean)
        manifest = svc.freeze(COURSE_ID)
        assert manifest["status"] == "FROZEN"
        assert session.scalar(select(ResourceDeliveryManifest).where(ResourceDeliveryManifest.course_id == COURSE_ID)) is not None
        session.execute(delete(ResourceDeliveryManifest).where(ResourceDeliveryManifest.course_id == COURSE_ID))
        session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.event_type == "resource.delivery.frozen", DomainEventOutbox.aggregate_id == COURSE_ID))
        session.commit()
