from __future__ import annotations

import hashlib
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
from app.resources.media import probe_local_video
from app.resources.models import (
    LabFilePack,
    LessonResource,
    PptAsset,
    Question,
    QuestionBank,
    QuestionExplanation,
    QuestionLessonMap,
    QuestionOption,
    QuestionReview,
    Resource,
    ResourceQualityCheck,
    ResourceReview,
    ResourceVersion,
    VideoAsset,
)
from app.teaching.catalog import curriculum_rows
from app.teaching.models import Course, CourseChapter, CourseLesson


pytestmark = pytest.mark.skipif(
    not os.getenv("YUEKE_DATABASE_URL"),
    reason="需要专属 MySQL（关系型数据库）集成库",
)

ROOT = Path(__file__).resolve().parents[2]
VIDEO_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "course-videos-v1"
INDEX_PATH = VIDEO_DIR / "index.json"
QUESTION_TYPES = ("FILL", "SINGLE", "MULTIPLE", "TRUE_FALSE")


def headers(user_id: str, course_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-Role": "teacher",
        "X-Teacher-Id": user_id,
        "X-Course-Ids": course_id,
        "X-Permissions": "resources:read,resources:write,resources:review,resources:freeze",
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_verify_index() -> dict:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    assert index["schema_version"] == "1.0"
    assert index["content_version"] == "1.0.0"
    assert index["complete"] is True
    assert (index["video_count"], index["theory_count"], index["lab_count"]) == (49, 37, 12)
    assert len(index["videos"]) == 49
    authority = {
        row["lesson_id"]: (row["lesson_code"], row["lesson_type"], row["title"])
        for row in curriculum_rows(index["course_id"])["lessons"]
    }
    assert {item["lesson_id"] for item in index["videos"]} == set(authority)
    for item in index["videos"]:
        assert (item["lesson_code"], item["lesson_kind"], item["title"]) == authority[item["lesson_id"]]
        path = VIDEO_DIR / item["filename"]
        assert path.stat().st_size == item["size_bytes"]
        assert file_sha256(path) == item["sha256"]
        duration, width, height = probe_local_video(str(path))
        assert abs(duration - item["duration_seconds"]) <= 1
        assert (width, height) == (item["width"], item["height"])
        if item["lesson_kind"] == "THEORY":
            assert 2100 <= duration <= 2700
        else:
            assert duration >= 600
    return index


def seed_prerequisite_content(
    session: Session,
    *,
    course_id: str,
    lessons: list[CourseLesson],
    author_id: str,
    reviewer_id: str,
    suffix: str,
) -> tuple[list[str], list[str], list[str]]:
    """Seed already-covered PPT/question/lab-pack gates; this test targets video APIs."""
    stamp = datetime.utcnow()
    resource_ids: list[str] = []
    file_ids: list[str] = []
    question_ids: list[str] = []
    bank_id = f"qb_video_{suffix}"
    session.add(
        QuestionBank(
            question_bank_id=bank_id,
            course_id=course_id,
            name="视频正式链前置题库",
            status="PUBLISHED",
            created_by=author_id,
            created_at=stamp,
        )
    )
    session.flush()

    for lesson_no, lesson in enumerate(lessons, start=1):
        extension: LessonResource | None = None
        for type_no, question_type in enumerate(QUESTION_TYPES, start=1):
            question_id = str(uuid4())
            question_ids.append(question_id)
            session.add(
                Question(
                    question_id=question_id,
                    question_bank_id=bank_id,
                    import_job_id=None,
                    source_row_number=None,
                    question_type=question_type,
                    stem=f"{lesson.lesson_code} {question_type} 视频链前置题",
                    answer_json={"answers": ["A"]},
                    status="PUBLISHED",
                    created_by=author_id,
                    created_at=stamp,
                    submitted_at=stamp,
                    reviewed_by=reviewer_id,
                    reviewed_at=stamp,
                )
            )
            session.flush()
            session.add(
                QuestionExplanation(
                    question_id=question_id,
                    explanation="独立审核通过的前置题库证据",
                )
            )
            session.add(
                QuestionLessonMap(
                    question_lesson_map_id=str(uuid4()),
                    question_id=question_id,
                    lesson_id=lesson.lesson_id,
                )
            )
            session.add(
                QuestionOption(
                    question_option_id=str(uuid4()),
                    question_id=question_id,
                    option_key="A",
                    option_text="参考答案",
                    is_correct=True,
                )
            )
            session.add(
                QuestionReview(
                    question_review_id=str(uuid4()),
                    question_id=question_id,
                    decision="APPROVED",
                    comment="前置题库独立审核通过",
                    reviewer_id=reviewer_id,
                    reviewed_at=stamp,
                )
            )

        if lesson.lesson_type == "THEORY":
            resource_type = "PPT"
            name = f"{lesson.lesson_code} 视频链前置课件"
        else:
            resource_type = "LAB_FILE"
            name = f"{lesson.lesson_code} 视频链前置实验包"
            extension = LessonResource(
                lesson_resource_id=str(uuid4()),
                course_id=course_id,
                lesson_id=lesson.lesson_id,
                purpose="完成本实验的安全目标",
                environment="隔离实验环境",
                principle="依据实验原理验证结果",
                steps_summary="准备、执行、验证、清理",
                core_experiment="视频正式链",
                linked_file_pack_id=None,
                linked_video_resource_id=None,
                linked_lab_definition_id=None,
            )
            session.add(extension)

        resource_id = str(uuid4())
        version_id = str(uuid4())
        file_id = str(uuid4())
        resource_ids.append(resource_id)
        file_ids.append(file_id)
        content_hash = hashlib.sha256(f"{suffix}:{lesson.lesson_id}:{resource_type}".encode()).hexdigest()
        session.add_all(
            [
                FileObject(
                    file_id=file_id,
                    storage_provider="local",
                    bucket="course-resources",
                    object_key=str(VIDEO_DIR / f"prerequisite-{suffix}-{lesson_no}-{resource_type.lower()}"),
                    original_name=f"prerequisite-{lesson_no}.{('pptx' if resource_type == 'PPT' else 'zip')}",
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        if resource_type == "PPT"
                        else "application/zip"
                    ),
                    size_bytes=1000 + lesson_no,
                    sha256=content_hash,
                    created_by=author_id,
                    created_at=stamp,
                ),
                Resource(
                    resource_id=resource_id,
                    course_id=course_id,
                    lesson_id=lesson.lesson_id,
                    name=name,
                    resource_type=resource_type,
                    status="PUBLISHED",
                    created_by=author_id,
                    created_at=stamp,
                    updated_at=stamp,
                ),
            ]
        )
        session.flush()
        session.add(
            ResourceVersion(
                resource_version_id=version_id,
                resource_id=resource_id,
                version_no=1,
                file_id=file_id,
                status="PUBLISHED",
                sha256=content_hash,
                created_by=author_id,
                created_at=stamp,
                reviewed_by=reviewer_id,
                reviewed_at=stamp,
                published_at=stamp,
            )
        )
        session.flush()
        session.add(
            ResourceReview(
                resource_review_id=str(uuid4()),
                resource_version_id=version_id,
                decision="APPROVED",
                comment="视频正式链前置资源独立审核通过",
                reviewer_id=reviewer_id,
                reviewed_at=stamp,
            )
        )
        if resource_type == "PPT":
            session.add(
                PptAsset(
                    ppt_asset_id=str(uuid4()),
                    resource_version_id=version_id,
                    knowledge_complete=True,
                    layout_overflow_passed=True,
                    animation_occlusion_passed=True,
                    copyright_noted=True,
                    checked_by=reviewer_id,
                    checked_at=stamp,
                )
            )
        else:
            pack_id = str(uuid4())
            session.add(
                LabFilePack(
                    lab_file_pack_id=pack_id,
                    resource_version_id=version_id,
                    file_count=1,
                    total_size_bytes=1000 + lesson_no,
                )
            )
            assert extension is not None
            extension.linked_file_pack_id = pack_id
    session.commit()
    return resource_ids, file_ids, question_ids


def test_formal_course_videos_real_mysql_upload_probe_review_publish_and_full_audit(tmp_path, monkeypatch):
    index = load_and_verify_index()
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("YUEKE_RESOURCE_UPLOAD_DIR", str(upload_dir))
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    suffix = uuid4().hex[:10]
    course_id = f"course_videos_{suffix}"
    author_id = f"video_author_{suffix}"
    reviewer_id = f"video_reviewer_{suffix}"
    author = headers(author_id, course_id)
    reviewer = headers(reviewer_id, course_id)
    video_resource_ids: list[str] = []
    prerequisite_resource_ids: list[str] = []
    file_ids: list[str] = []
    question_ids: list[str] = []

    authority = curriculum_rows(course_id)
    with Session(engine) as session:
        session.add(
            Course(
                course_id=course_id,
                name="数据安全技术基础",
                term="2026 秋季",
                owner_teacher_id=author_id,
                major="网络空间安全",
                description="课程视频正式链专用测试课程",
                status="ACTIVE",
                created_at=datetime.utcnow(),
            )
        )
        session.add_all(CourseChapter(**row) for row in authority["chapters"])
        session.add_all(CourseLesson(**row) for row in authority["lessons"])
        session.commit()
        lessons = list(session.scalars(select(CourseLesson).where(CourseLesson.course_id == course_id)))
        assert len(lessons) == 49
        prerequisite_resource_ids, prerequisite_file_ids, question_ids = seed_prerequisite_content(
            session,
            course_id=course_id,
            lessons=lessons,
            author_id=author_id,
            reviewer_id=reviewer_id,
            suffix=suffix,
        )
        file_ids.extend(prerequisite_file_ids)
        lesson_ids_by_code = {row.lesson_code: row.lesson_id for row in lessons}

    client = TestClient(app)
    try:
        for number, entry in enumerate(index["videos"]):
            source_path = VIDEO_DIR / entry["filename"]
            owns_file_object = False
            if number == 0:
                upload_path = tmp_path / f"{suffix}-{entry['filename']}"
                upload_path.write_bytes(source_path.read_bytes() + f"\nYUEKE-TEST-{suffix}\n".encode())
                with upload_path.open("rb") as video_stream:
                    uploaded = client.post(
                        "/api/v1/resources/files",
                        headers=author,
                        data={"course_id": course_id},
                        files={"file": (entry["filename"], video_stream, "video/mp4")},
                    )
                assert uploaded.status_code == 201, uploaded.text
                file_data = uploaded.json()
                assert file_data["sha256"] != entry["sha256"]
                assert file_data["size_bytes"] > entry["size_bytes"]
                owns_file_object = True
            else:
                with Session(engine) as session:
                    file_object = session.scalar(select(FileObject).where(FileObject.sha256 == entry["sha256"]))
                    if file_object:
                        file_data = {"file_id": file_object.file_id, "sha256": file_object.sha256}
                    else:
                        file_data = {"file_id": str(uuid4()), "sha256": entry["sha256"]}
                        session.add(
                            FileObject(
                                file_id=file_data["file_id"],
                                storage_provider="local",
                                bucket="course-resources",
                                object_key=str(source_path),
                                original_name=entry["filename"],
                                mime_type="video/mp4",
                                size_bytes=entry["size_bytes"],
                                sha256=entry["sha256"],
                                created_by=author_id,
                                created_at=datetime.utcnow(),
                            )
                        )
                        owns_file_object = True
                        session.commit()
            if owns_file_object:
                file_ids.append(file_data["file_id"])

            created = client.post(
                "/api/v1/resources",
                headers=author,
                json={
                    "course_id": course_id,
                    "lesson_id": lesson_ids_by_code[entry["lesson_code"]],
                    "name": f"{entry['lesson_code']} {entry['title']} 视频正式链 {suffix}",
                    "resource_type": "VIDEO",
                },
            )
            assert created.status_code == 201, created.text
            resource_id = created.json()["resource_id"]
            video_resource_ids.append(resource_id)

            version = client.post(
                f"/api/v1/resources/{resource_id}/versions",
                headers=author,
                json={"file_id": file_data["file_id"], "sha256": file_data["sha256"]},
            )
            assert version.status_code == 201, version.text
            version_data = version.json()
            version_id = version_data["resource_version_id"]
            assert version_data["video"]["duration_seconds"] == entry["duration_seconds"]
            assert (version_data["video"]["width"], version_data["video"]["height"]) == (
                entry["width"],
                entry["height"],
            )
            latest = client.get(f"/api/v1/resources/{resource_id}", headers=author)
            assert latest.status_code == 200, latest.text
            latest_video = latest.json()["latest_version"]["video"]
            assert latest_video["duration_seconds"] == entry["duration_seconds"]
            assert (latest_video["width"], latest_video["height"]) == (entry["width"], entry["height"])
            with Session(engine) as session:
                asset = session.scalar(select(VideoAsset).where(VideoAsset.resource_version_id == version_id))
                assert asset is not None
                assert abs(asset.duration_seconds - entry["duration_seconds"]) <= 1
                assert (asset.width, asset.height) == (entry["width"], entry["height"])
                assert asset.probed_at is not None

            submitted = client.post(f"/api/v1/resources/{resource_id}/submit-review", headers=author)
            assert submitted.status_code == 200, submitted.text
            if number == 0:
                self_review = client.post(
                    f"/api/v1/resources/{resource_id}/approve",
                    headers=author,
                    json={"comment": "验证制作者不能审核自己的视频"},
                )
                assert self_review.status_code == 409, self_review.text
                assert self_review.json()["code"] == "RESOURCE.REVIEWER_MUST_BE_INDEPENDENT"

            approved = client.post(
                f"/api/v1/resources/{resource_id}/approve",
                headers=reviewer,
                json={"comment": "真实媒体、时长、画面与课时映射复核通过"},
            )
            assert approved.status_code == 200, approved.text
            published = client.post(f"/api/v1/resources/{resource_id}/publish", headers=author)
            assert published.status_code == 200, published.text
            assert published.json()["status"] == "PUBLISHED"

            if entry["lesson_kind"] == "LAB":
                with Session(engine) as session:
                    extension = session.scalar(
                        select(LessonResource).where(
                            LessonResource.course_id == course_id,
                            LessonResource.lesson_id == lesson_ids_by_code[entry["lesson_code"]],
                        )
                    )
                    assert extension is not None
                    extension.linked_video_resource_id = resource_id
                    session.commit()

        readiness = client.get(
            "/api/v1/resources/readiness",
            headers=reviewer,
            params={"course_id": course_id},
        )
        assert readiness.status_code == 200, readiness.text
        readiness_data = readiness.json()
        assert readiness_data["theory_video"] == {"ready": 37, "required": 37}
        assert readiness_data["lab_video"] == {"ready": 12, "required": 12}
        assert readiness_data["blocking"] == 0

        audited = client.post(
            "/api/v1/resources/audit/run",
            headers=reviewer,
            json={"course_id": course_id},
        )
        assert audited.status_code == 200, audited.text
        assert (audited.json()["total"], audited.json()["pass"], audited.json()["blocking"]) == (196, 196, 0)
        assert audited.json()["blocking_items"] == []

        with Session(engine) as session:
            version_ids = list(
                session.scalars(
                    select(ResourceVersion.resource_version_id).where(
                        ResourceVersion.resource_id.in_(video_resource_ids)
                    )
                )
            )
            assert session.scalar(
                select(func.count()).select_from(VideoAsset).where(VideoAsset.resource_version_id.in_(version_ids))
            ) == 49
            assert session.scalar(
                select(func.count()).select_from(ResourceReview).where(
                    ResourceReview.resource_version_id.in_(version_ids),
                    ResourceReview.decision == "APPROVED",
                    ResourceReview.reviewer_id == reviewer_id,
                )
            ) == 49
    finally:
        all_resource_ids = prerequisite_resource_ids + video_resource_ids
        with Session(engine) as session:
            session.execute(delete(ResourceQualityCheck).where(ResourceQualityCheck.course_id == course_id))
            session.execute(delete(QuestionReview).where(QuestionReview.question_id.in_(question_ids)))
            session.execute(delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids)))
            session.execute(delete(QuestionExplanation).where(QuestionExplanation.question_id.in_(question_ids)))
            session.execute(delete(QuestionLessonMap).where(QuestionLessonMap.question_id.in_(question_ids)))
            session.execute(delete(Question).where(Question.question_id.in_(question_ids)))
            session.execute(delete(QuestionBank).where(QuestionBank.course_id == course_id))
            session.execute(delete(LessonResource).where(LessonResource.course_id == course_id))
            version_ids = list(
                session.scalars(
                    select(ResourceVersion.resource_version_id).where(
                        ResourceVersion.resource_id.in_(all_resource_ids)
                    )
                )
            ) if all_resource_ids else []
            if version_ids:
                session.execute(delete(VideoAsset).where(VideoAsset.resource_version_id.in_(version_ids)))
                session.execute(delete(PptAsset).where(PptAsset.resource_version_id.in_(version_ids)))
                session.execute(delete(LabFilePack).where(LabFilePack.resource_version_id.in_(version_ids)))
                session.execute(delete(ResourceReview).where(ResourceReview.resource_version_id.in_(version_ids)))
                session.execute(delete(ResourceVersion).where(ResourceVersion.resource_version_id.in_(version_ids)))
            if all_resource_ids:
                session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.aggregate_id.in_(all_resource_ids)))
                session.execute(delete(Resource).where(Resource.resource_id.in_(all_resource_ids)))
            session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.aggregate_id == course_id))
            if file_ids:
                session.execute(delete(FileObject).where(FileObject.file_id.in_(file_ids)))
            session.execute(delete(CourseLesson).where(CourseLesson.course_id == course_id))
            session.execute(delete(CourseChapter).where(CourseChapter.course_id == course_id))
            session.execute(delete(Course).where(Course.course_id == course_id))
            session.commit()
