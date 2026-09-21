from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.models import FileObject
from app.main import app
from app.resources.models import PptAsset, Resource, ResourceQualityCheck, ResourceReview, ResourceVersion
from app.resources.service import ResourceService
from app.teaching.catalog import COURSE_ID, curriculum_rows
from app.teaching.models import Course, CourseChapter, CourseLesson


ROOT = Path(__file__).resolve().parents[1]
DECK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "theory-ppts-v1"
INDEX_PATH = DECK_DIR / "index.json"
EXPECTED_DATABASE = "yueke_question_bank_content_v101_dev"
CONTENT_VERSION = "1.0.0"
AUTHOR_ID = "content_author_b"
REVIEWER_ID = "content_reviewer_b"


def headers(user_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-Role": "teacher",
        "X-Teacher-Id": user_id,
        "X-Course-Ids": COURSE_ID,
        "X-Permissions": "resources:read,resources:write,resources:review,resources:freeze",
    }


database_url = os.environ["YUEKE_DATABASE_URL"]
database_name = make_url(database_url).database
if database_name != EXPECTED_DATABASE:
    raise RuntimeError(f"理论课件脚本只允许写入隔离开发库 {EXPECTED_DATABASE}，当前为 {database_name}")

index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
if index["course_id"] != COURSE_ID or index["content_version"] != CONTENT_VERSION or index["deck_count"] != 37:
    raise RuntimeError("理论课件索引不是固定课程的正式 v1.0.0 版本")
for entry in index["decks"]:
    content = (DECK_DIR / entry["filename"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != entry["sha256"] or len(content) != entry["size_bytes"]:
        raise RuntimeError(f"理论课件校验值或文件大小不匹配：{entry['filename']}")

engine = create_engine(database_url)
with Session(engine) as session:
    course = session.get(Course, COURSE_ID)
    chapters = list(session.scalars(select(CourseChapter).where(CourseChapter.course_id == COURSE_ID)))
    lessons = list(session.scalars(select(CourseLesson).where(CourseLesson.course_id == COURSE_ID)))
    expected = curriculum_rows(COURSE_ID)
    expected_chapters = {(row["sequence"], row["title"]) for row in expected["chapters"]}
    actual_chapters = {(row.sequence, row.title) for row in chapters}
    expected_lessons = {
        row["lesson_code"]: (row["lesson_type"], row["title"])
        for row in expected["lessons"]
    }
    actual_lessons = {
        row.lesson_code: (row.lesson_type, row.title)
        for row in lessons
    }
    if course is None:
        raise RuntimeError("A 线权威课程不存在，拒绝由 B 线课件脚本创建课程事实")
    if len(chapters) != 8 or actual_chapters != expected_chapters:
        raise RuntimeError(f"A 线权威章节目录不完整，要求8章，当前为{len(chapters)}章")
    if len(lessons) != 49 or actual_lessons != expected_lessons:
        raise RuntimeError(f"A 线权威课时目录不完整，要求49课时，当前为{len(lessons)}课时")
    lesson_ids_by_code = {row.lesson_code: row.lesson_id for row in lessons}

client = TestClient(app)
author_headers = headers(AUTHOR_ID)
reviewer_headers = headers(REVIEWER_ID)
resource_ids: list[str] = []
self_review_denial_verified = False

for entry in index["decks"]:
    lesson_id = lesson_ids_by_code.get(entry["lesson_code"])
    if lesson_id is None:
        raise RuntimeError(f"A 线权威目录缺少理论课时 {entry['lesson_code']}")
    expected_name = f"{entry['lesson_code']} {entry['display_title']} 正式理论课件 v{CONTENT_VERSION}"
    with Session(engine) as session:
        existing = list(
            session.scalars(
                select(Resource).where(
                    Resource.course_id == COURSE_ID,
                    Resource.lesson_id == lesson_id,
                    Resource.resource_type == "PPT",
                )
            )
        )
    if len(existing) > 1:
        raise RuntimeError(f"{entry['lesson_code']} 已有多个理论课件资源，脚本拒绝覆盖")

    if existing:
        resource_id = existing[0].resource_id
    else:
        deck_bytes = (DECK_DIR / entry["filename"]).read_bytes()
        uploaded = client.post(
            "/api/v1/resources/files",
            headers=author_headers,
            data={"course_id": COURSE_ID},
            files={
                "file": (
                    entry["filename"],
                    deck_bytes,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )
        uploaded.raise_for_status()
        file_data = uploaded.json()

        created = client.post(
            "/api/v1/resources",
            headers=author_headers,
            json={
                "course_id": COURSE_ID,
                "lesson_id": lesson_id,
                "name": expected_name,
                "resource_type": "PPT",
            },
        )
        created.raise_for_status()
        resource_id = created.json()["resource_id"]

        version_response = client.post(
            f"/api/v1/resources/{resource_id}/versions",
            headers=author_headers,
            json={"file_id": file_data["file_id"], "sha256": file_data["sha256"]},
        )
        version_response.raise_for_status()
        version_id = version_response.json()["resource_version_id"]

        quality = client.post(
            f"/api/v1/resources/{resource_id}/versions/{version_id}/quality-check",
            headers=reviewer_headers,
            json={
                "knowledge_complete": True,
                "layout_overflow_passed": True,
                "animation_occlusion_passed": True,
                "copyright_noted": True,
            },
        )
        quality.raise_for_status()
        if quality.json()["result"] != "PASS":
            raise RuntimeError(f"{entry['lesson_code']} 四项课件质量检查未通过")

        submitted = client.post(f"/api/v1/resources/{resource_id}/submit-review", headers=author_headers)
        submitted.raise_for_status()
        if not self_review_denial_verified:
            self_review = client.post(
                f"/api/v1/resources/{resource_id}/approve",
                headers=author_headers,
                json={"comment": "验证制作者不能审核自己的课件"},
            )
            if self_review.status_code != 409 or self_review.json().get("code") != "RESOURCE.REVIEWER_MUST_BE_INDEPENDENT":
                raise RuntimeError(f"理论课件独立审核门禁未生效：{self_review.text}")
            self_review_denial_verified = True

        approved = client.post(
            f"/api/v1/resources/{resource_id}/approve",
            headers=reviewer_headers,
            json={"comment": "课时知识点、逐页版式、无动画遮挡和来源标注复核通过"},
        )
        approved.raise_for_status()
        published = client.post(f"/api/v1/resources/{resource_id}/publish", headers=author_headers)
        published.raise_for_status()

    resource_ids.append(resource_id)

    with Session(engine) as session:
        resource = session.get(Resource, resource_id)
        version = session.scalar(
            select(ResourceVersion)
            .where(ResourceVersion.resource_id == resource_id)
            .order_by(ResourceVersion.version_no.desc())
            .limit(1)
        )
        file_object = session.get(FileObject, version.file_id) if version else None
        asset = session.scalar(select(PptAsset).where(PptAsset.resource_version_id == version.resource_version_id)) if version else None
        review = session.scalar(
            select(ResourceReview).where(
                ResourceReview.resource_version_id == version.resource_version_id,
                ResourceReview.decision == "APPROVED",
            )
        ) if version else None
        quality = session.scalar(
            select(ResourceQualityCheck).where(
                ResourceQualityCheck.resource_version_id == version.resource_version_id,
                ResourceQualityCheck.check_type == "PPT_MANUAL_REVIEW",
                ResourceQualityCheck.result == "PASS",
            )
        ) if version else None
        valid = bool(
            resource
            and resource.name == expected_name
            and resource.status == "PUBLISHED"
            and resource.created_by == AUTHOR_ID
            and version
            and version.status == "PUBLISHED"
            and version.created_by == AUTHOR_ID
            and version.sha256 == entry["sha256"]
            and file_object
            and file_object.sha256 == entry["sha256"]
            and file_object.size_bytes == entry["size_bytes"]
            and asset
            and asset.knowledge_complete
            and asset.layout_overflow_passed
            and asset.animation_occlusion_passed
            and asset.copyright_noted
            and asset.checked_by == REVIEWER_ID
            and asset.checked_at
            and review
            and review.reviewer_id == REVIEWER_ID
            and review.reviewer_id != version.created_by
            and quality
            and quality.checked_by == REVIEWER_ID
        )
        if not valid:
            raise RuntimeError(f"{entry['lesson_code']} 已有资源与正式课件 v{CONTENT_VERSION} 不一致，脚本拒绝覆盖")

with Session(engine) as session:
    total_ppt_resources = session.scalar(
        select(func.count()).select_from(Resource).where(Resource.course_id == COURSE_ID, Resource.resource_type == "PPT")
    )
    context = UserContext(
        REVIEWER_ID,
        "teacher",
        REVIEWER_ID,
        None,
        frozenset({"resources:read", "resources:write", "resources:review", "resources:freeze"}),
        frozenset({COURSE_ID}),
        frozenset(),
    )
    audit = ResourceService(session, context).audit(COURSE_ID, persist=False)

readiness_response = client.get("/api/v1/resources/readiness", headers=reviewer_headers, params={"course_id": COURSE_ID})
readiness_response.raise_for_status()
readiness = readiness_response.json()

result = {
    "database": database_name,
    "course_id": COURSE_ID,
    "content_version": CONTENT_VERSION,
    "theory_ppt_count": len(resource_ids),
    "published_ppt_resource_count": total_ppt_resources,
    "readiness": {"ppt": readiness["ppt"]},
    "course_audit": {"total": audit["total"], "pass": audit["pass"], "blocking": audit["blocking"]},
    "author_identity": AUTHOR_ID,
    "independent_reviewer_identity": REVIEWER_ID,
    "review_boundary": "系统账号隔离、逐页视觉检查、四项质量记录与独立审核已验证；未宣称外部教研专家人工验收",
}
if len(set(resource_ids)) != 37 or total_ppt_resources != 37:
    raise RuntimeError(f"正式理论课件资源数量不正确：{result}")
if readiness["ppt"] != {"ready": 37, "required": 37}:
    raise RuntimeError(f"正式理论课件就绪度不正确：{result}")
if audit["total"] != 196 or audit["pass"] < 110 or audit["blocking"] != 196 - audit["pass"]:
    raise RuntimeError(f"课程动态审计未达到题库、实验包和理论课件基线：{result}")
print(json.dumps(result, ensure_ascii=False, indent=2))
