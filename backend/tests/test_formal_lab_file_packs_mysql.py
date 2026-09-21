from __future__ import annotations

import json
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox, FileObject
from app.main import app
from app.resources.models import (
    LabFilePack,
    LessonResource,
    Resource,
    ResourceQualityCheck,
    ResourceReview,
    ResourceVersion,
)
from app.teaching.catalog import curriculum_rows
from app.teaching.models import Course, CourseChapter, CourseLesson


pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL（关系型数据库）集成库")

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "lab-file-packs-v1"
INDEX = json.loads((PACK_DIR / "index.json").read_text(encoding="utf-8"))


def headers(user_id: str, course_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-Role": "teacher",
        "X-Teacher-Id": user_id,
        "X-Course-Ids": course_id,
        "X-Permissions": "resources:read,resources:write,resources:review,resources:freeze",
    }


def isolated_archive(entry: dict, suffix: str) -> bytes:
    """Keep the formal pack intact while avoiding content collisions in repeatable DB tests."""
    source_path = PACK_DIR / entry["filename"]
    target = BytesIO()
    with ZipFile(source_path) as source, ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for info in source.infolist():
            archive.writestr(info, source.read(info.filename))
        archive.writestr("mysql-integration-marker.txt", f"isolated-test-{suffix}\n")
    return target.getvalue()


def test_formal_lab_file_packs_upload_review_publish_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEKE_RESOURCE_UPLOAD_DIR", str(tmp_path / "uploads"))
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    suffix = uuid4().hex[:10]
    course_id = f"course_lab_packs_{suffix}"
    author = headers(f"lab_author_{suffix}", course_id)
    reviewer = headers(f"lab_reviewer_{suffix}", course_id)
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
                description=None,
                status="ACTIVE",
                created_at=datetime.utcnow(),
            )
        )
        authority = curriculum_rows(course_id)
        session.add_all(CourseChapter(**row) for row in authority["chapters"])
        session.add_all(CourseLesson(**row) for row in authority["lessons"])
        session.commit()
    lesson_ids = {row["lesson_code"]: row["lesson_id"] for row in authority["lessons"]}

    client = TestClient(app)
    try:
        for number, entry in enumerate(INDEX["packs"]):
            lesson_id = lesson_ids[entry["lesson_code"]]
            content = isolated_archive(entry, suffix)
            uploaded = client.post(
                "/api/v1/resources/files",
                headers=author,
                data={"course_id": course_id},
                files={"file": (entry["filename"], content, "application/zip")},
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
                    "resource_type": "LAB_FILE",
                },
            )
            assert created.status_code == 201, created.text
            resource_id = created.json()["resource_id"]
            resource_ids.append(resource_id)

            version = client.post(
                f"/api/v1/resources/{resource_id}/versions",
                headers=author,
                json={
                    "file_id": file_data["file_id"],
                    "sha256": file_data["sha256"],
                    "lab_file_count": entry["file_count"] + 1,
                },
            )
            assert version.status_code == 201, version.text
            submitted = client.post(f"/api/v1/resources/{resource_id}/submit-review", headers=author)
            assert submitted.status_code == 200, submitted.text

            if number == 0:
                self_review = client.post(
                    f"/api/v1/resources/{resource_id}/approve",
                    headers=author,
                    json={"comment": "制作者不能审核自己的资源"},
                )
                assert self_review.status_code == 409
                assert self_review.json()["code"] == "RESOURCE.REVIEWER_MUST_BE_INDEPENDENT"

            approved = client.post(
                f"/api/v1/resources/{resource_id}/approve",
                headers=reviewer,
                json={"comment": "文件清单、校验值与可执行验证链路复核通过"},
            )
            assert approved.status_code == 200, approved.text
            published = client.post(f"/api/v1/resources/{resource_id}/publish", headers=author)
            assert published.status_code == 200, published.text
            assert published.json()["status"] == "PUBLISHED"

        readiness = client.get("/api/v1/resources/readiness", headers=reviewer, params={"course_id": course_id})
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["lab_file"] == {"ready": 12, "required": 12}
        assert readiness.json()["blocking"] == 184

        audit = client.post("/api/v1/resources/audit/run", headers=reviewer, json={"course_id": course_id})
        assert audit.status_code == 200, audit.text
        assert (audit.json()["total"], audit.json()["pass"], audit.json()["blocking"]) == (196, 12, 184)

        downloaded = client.get(f"/api/v1/resources/{resource_ids[0]}/download", headers=reviewer)
        assert downloaded.status_code == 200
        with ZipFile(BytesIO(downloaded.content)) as archive:
            assert "pack-manifest.json" in archive.namelist()

        with Session(engine) as session:
            version_ids = list(
                session.scalars(select(ResourceVersion.resource_version_id).where(ResourceVersion.resource_id.in_(resource_ids)))
            )
            assert session.scalar(select(func.count()).select_from(LabFilePack).where(LabFilePack.resource_version_id.in_(version_ids))) == 12
            assert session.scalar(select(func.count()).select_from(ResourceReview).where(ResourceReview.resource_version_id.in_(version_ids), ResourceReview.decision == "APPROVED")) == 12
            links = list(
                session.scalars(
                    select(LessonResource.linked_file_pack_id).where(
                        LessonResource.course_id == course_id,
                    )
                )
            )
            assert len(links) == 12 and all(links) and len(set(links)) == 12
    finally:
        with Session(engine) as session:
            version_ids = list(
                session.scalars(select(ResourceVersion.resource_version_id).where(ResourceVersion.resource_id.in_(resource_ids)))
            ) if resource_ids else []
            if version_ids:
                session.execute(delete(ResourceReview).where(ResourceReview.resource_version_id.in_(version_ids)))
                session.execute(delete(LabFilePack).where(LabFilePack.resource_version_id.in_(version_ids)))
                session.execute(delete(ResourceVersion).where(ResourceVersion.resource_version_id.in_(version_ids)))
            if resource_ids:
                session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.aggregate_id.in_(resource_ids)))
                session.execute(delete(Resource).where(Resource.resource_id.in_(resource_ids)))
            if file_ids:
                session.execute(delete(FileObject).where(FileObject.file_id.in_(file_ids)))
            session.execute(delete(ResourceQualityCheck).where(ResourceQualityCheck.course_id == course_id))
            session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.aggregate_id == course_id))
            session.execute(delete(LessonResource).where(LessonResource.course_id == course_id))
            session.execute(delete(CourseLesson).where(CourseLesson.course_id == course_id))
            session.execute(delete(CourseChapter).where(CourseChapter.course_id == course_id))
            session.execute(delete(Course).where(Course.course_id == course_id))
            session.commit()
