from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox, FileObject
from app.main import app
from app.resources.models import PptAsset, Resource, ResourceQualityCheck, ResourceReview, ResourceVersion
from app.teaching.catalog import curriculum_rows
from app.teaching.models import Course, CourseChapter, CourseLesson


pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL（关系型数据库）集成库")

ROOT = Path(__file__).resolve().parents[2]
DECK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "theory-ppts-v1"
INDEX = json.loads((DECK_DIR / "index.json").read_text(encoding="utf-8"))


def headers(user_id: str, course_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-Role": "teacher",
        "X-Teacher-Id": user_id,
        "X-Course-Ids": course_id,
        "X-Permissions": "resources:read,resources:write,resources:review,resources:freeze",
    }


def test_formal_theory_ppts_upload_quality_review_publish_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEKE_RESOURCE_UPLOAD_DIR", str(tmp_path / "uploads"))
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    suffix = uuid4().hex[:10]
    course_id = f"course_theory_ppts_{suffix}"
    author = headers(f"ppt_author_{suffix}", course_id)
    reviewer = headers(f"ppt_reviewer_{suffix}", course_id)
    resource_ids: list[str] = []
    file_ids: list[str] = []

    with Session(engine) as session:
        session.add(
            Course(
                course_id=course_id,
                name="数据安全技术基础",
                term="2026 秋季",
                owner_teacher_id=author["X-Teacher-Id"],
                major="网络空间安全",
                description="正式理论课件集成验证课程",
                status="ACTIVE",
                created_at=datetime.utcnow(),
            )
        )
        authority = curriculum_rows(course_id)
        session.add_all(CourseChapter(**row) for row in authority["chapters"])
        session.add_all(CourseLesson(**row) for row in authority["lessons"])
        session.commit()
        lessons = list(session.scalars(select(CourseLesson).where(CourseLesson.course_id == course_id)))
        assert len(lessons) == 49
        assert sum(row.lesson_type == "THEORY" for row in lessons) == 37
        assert sum(row.lesson_type == "LAB" for row in lessons) == 12
        lesson_ids_by_code = {row.lesson_code: row.lesson_id for row in lessons}

    client = TestClient(app)
    try:
        for number, entry in enumerate(INDEX["decks"]):
            lesson_id = lesson_ids_by_code[entry["lesson_code"]]
            content = (DECK_DIR / entry["filename"]).read_bytes() + f"\nmysql-integration-{suffix}\n".encode()
            uploaded = client.post(
                "/api/v1/resources/files",
                headers=author,
                data={"course_id": course_id},
                files={"file": (entry["filename"], content, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
            )
            assert uploaded.status_code == 201, uploaded.text
            file_data = uploaded.json()
            file_ids.append(file_data["file_id"])

            created = client.post(
                "/api/v1/resources",
                headers=author,
                json={
                    "course_id": course_id,
                    "lesson_id": lesson_id,
                    "name": f"{entry['lesson_code']} {entry['title']} 集成验证 {suffix}",
                    "resource_type": "PPT",
                },
            )
            assert created.status_code == 201, created.text
            resource_id = created.json()["resource_id"]
            resource_ids.append(resource_id)

            version = client.post(
                f"/api/v1/resources/{resource_id}/versions",
                headers=author,
                json={"file_id": file_data["file_id"], "sha256": file_data["sha256"]},
            )
            assert version.status_code == 201, version.text
            version_id = version.json()["resource_version_id"]

            quality = client.post(
                f"/api/v1/resources/{resource_id}/versions/{version_id}/quality-check",
                headers=reviewer,
                json={
                    "knowledge_complete": True,
                    "layout_overflow_passed": True,
                    "animation_occlusion_passed": True,
                    "copyright_noted": True,
                },
            )
            assert quality.status_code == 200 and quality.json()["result"] == "PASS", quality.text
            submitted = client.post(f"/api/v1/resources/{resource_id}/submit-review", headers=author)
            assert submitted.status_code == 200, submitted.text

            if number == 0:
                self_review = client.post(
                    f"/api/v1/resources/{resource_id}/approve",
                    headers=author,
                    json={"comment": "验证制作者不能审核自己的课件"},
                )
                assert self_review.status_code == 409
                assert self_review.json()["code"] == "RESOURCE.REVIEWER_MUST_BE_INDEPENDENT"

            approved = client.post(
                f"/api/v1/resources/{resource_id}/approve",
                headers=reviewer,
                json={"comment": "知识点、版式、无动画遮挡和来源标注复核通过"},
            )
            assert approved.status_code == 200, approved.text
            published = client.post(f"/api/v1/resources/{resource_id}/publish", headers=author)
            assert published.status_code == 200 and published.json()["status"] == "PUBLISHED", published.text

        readiness = client.get("/api/v1/resources/readiness", headers=reviewer, params={"course_id": course_id})
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["theory_lessons"] == 37
        assert readiness.json()["lab_lessons"] == 12
        assert readiness.json()["ppt"] == {"ready": 37, "required": 37}
        assert readiness.json()["blocking"] == 159

        downloaded = client.get(f"/api/v1/resources/{resource_ids[0]}/download", headers=reviewer)
        assert downloaded.status_code == 200 and downloaded.content.startswith(b"PK")

        with Session(engine) as session:
            version_ids = list(
                session.scalars(select(ResourceVersion.resource_version_id).where(ResourceVersion.resource_id.in_(resource_ids)))
            )
            assert session.scalar(select(func.count()).select_from(PptAsset).where(PptAsset.resource_version_id.in_(version_ids), PptAsset.knowledge_complete.is_(True), PptAsset.layout_overflow_passed.is_(True), PptAsset.animation_occlusion_passed.is_(True), PptAsset.copyright_noted.is_(True))) == 37
            assert session.scalar(select(func.count()).select_from(ResourceReview).where(ResourceReview.resource_version_id.in_(version_ids), ResourceReview.decision == "APPROVED")) == 37
    finally:
        with Session(engine) as session:
            version_ids = list(
                session.scalars(select(ResourceVersion.resource_version_id).where(ResourceVersion.resource_id.in_(resource_ids)))
            ) if resource_ids else []
            if version_ids:
                session.execute(delete(ResourceQualityCheck).where(ResourceQualityCheck.resource_version_id.in_(version_ids)))
                session.execute(delete(ResourceReview).where(ResourceReview.resource_version_id.in_(version_ids)))
                session.execute(delete(PptAsset).where(PptAsset.resource_version_id.in_(version_ids)))
                session.execute(delete(ResourceVersion).where(ResourceVersion.resource_version_id.in_(version_ids)))
            if resource_ids:
                session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.aggregate_id.in_(resource_ids)))
                session.execute(delete(Resource).where(Resource.resource_id.in_(resource_ids)))
            if file_ids:
                session.execute(delete(FileObject).where(FileObject.file_id.in_(file_ids)))
            session.execute(delete(CourseLesson).where(CourseLesson.course_id == course_id))
            session.execute(delete(CourseChapter).where(CourseChapter.course_id == course_id))
            session.execute(delete(Course).where(Course.course_id == course_id))
            session.commit()
