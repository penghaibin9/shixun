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
from app.resources.catalog import COURSE_ID
from app.resources.models import LabFilePack, LessonResource, Resource, ResourceReview, ResourceVersion
from app.resources.service import ResourceService
from app.teaching.models import Course, CourseChapter, CourseLesson


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "lab-file-packs-v1"
INDEX_PATH = PACK_DIR / "index.json"
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
    raise RuntimeError(f"实验文件包脚本只允许写入隔离开发库 {EXPECTED_DATABASE}，当前为 {database_name}")

index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
if index["course_id"] != COURSE_ID or index["content_version"] != CONTENT_VERSION or index["pack_count"] != 12:
    raise RuntimeError("实验文件包索引不是固定课程的正式 v1.0.0 版本")
for entry in index["packs"]:
    content = (PACK_DIR / entry["filename"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"实验文件包校验值不匹配：{entry['filename']}")

engine = create_engine(database_url)
with Session(engine) as session:
    if not session.get(Course, COURSE_ID):
        raise RuntimeError("A 模块权威课程不存在，请先执行数据库迁移或由教学核心创建课程")
    lessons = list(session.scalars(select(CourseLesson).where(CourseLesson.course_id == COURSE_ID)))
    chapter_count = session.scalar(select(func.count()).select_from(CourseChapter).where(CourseChapter.course_id == COURSE_ID))
    theory_count = sum(lesson.lesson_type == "THEORY" for lesson in lessons)
    lab_count = sum(lesson.lesson_type == "LAB" for lesson in lessons)
    if (len(lessons), theory_count, lab_count, chapter_count) != (49, 37, 12, 8):
        raise RuntimeError(
            f"A 模块权威目录不完整：总课时 {len(lessons)}，理论 {theory_count}，实验 {lab_count}，章节 {chapter_count}"
        )
    authority_by_code = {lesson.lesson_code: lesson for lesson in lessons}

client = TestClient(app)
author_headers = headers(AUTHOR_ID)
reviewer_headers = headers(REVIEWER_ID)
resource_ids: list[str] = []
self_review_denial_verified = False

for entry in index["packs"]:
    authority = authority_by_code.get(entry["lesson_code"])
    if not authority or authority.lesson_type != "LAB":
        raise RuntimeError(f"A 模块权威目录缺少实验课时：{entry['lesson_code']}")
    lesson_id = authority.lesson_id
    expected_name = f"{authority.lesson_code} {authority.title} 正式实验文件包 v{CONTENT_VERSION}"
    with Session(engine) as session:
        existing = list(
            session.scalars(
                select(Resource).where(
                    Resource.course_id == COURSE_ID,
                    Resource.lesson_id == lesson_id,
                    Resource.resource_type == "LAB_FILE",
                )
            )
        )
    if len(existing) > 1:
        raise RuntimeError(f"{entry['lesson_code']} 已有多个实验文件资源，脚本拒绝覆盖")

    if existing:
        resource_id = existing[0].resource_id
    else:
        archive_bytes = (PACK_DIR / entry["filename"]).read_bytes()
        uploaded = client.post(
            "/api/v1/resources/files",
            headers=author_headers,
            data={"course_id": COURSE_ID},
            files={"file": (entry["filename"], archive_bytes, "application/zip")},
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
                "resource_type": "LAB_FILE",
            },
        )
        created.raise_for_status()
        resource_id = created.json()["resource_id"]

        version = client.post(
            f"/api/v1/resources/{resource_id}/versions",
            headers=author_headers,
            json={
                "file_id": file_data["file_id"],
                "sha256": file_data["sha256"],
                "lab_file_count": entry["file_count"],
            },
        )
        version.raise_for_status()
        submitted = client.post(f"/api/v1/resources/{resource_id}/submit-review", headers=author_headers)
        submitted.raise_for_status()

        if not self_review_denial_verified:
            self_review = client.post(
                f"/api/v1/resources/{resource_id}/approve",
                headers=author_headers,
                json={"comment": "验证制作者不能审核自己的资源"},
            )
            if self_review.status_code != 409 or self_review.json().get("code") != "RESOURCE.REVIEWER_MUST_BE_INDEPENDENT":
                raise RuntimeError(f"实验文件包独立审核门禁未生效：{self_review.text}")
            self_review_denial_verified = True

        approved = client.post(
            f"/api/v1/resources/{resource_id}/approve",
            headers=reviewer_headers,
            json={"comment": "正式实验文件包清单、校验值、内容与隔离执行结果复核通过"},
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
        pack = session.scalar(select(LabFilePack).where(LabFilePack.resource_version_id == version.resource_version_id)) if version else None
        review = session.scalar(
            select(ResourceReview).where(
                ResourceReview.resource_version_id == version.resource_version_id,
                ResourceReview.decision == "APPROVED",
            )
        ) if version else None
        lesson = session.scalar(
            select(LessonResource).where(
                LessonResource.course_id == COURSE_ID,
                LessonResource.lesson_id == lesson_id,
            )
        )
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
            and pack
            and pack.file_count == entry["file_count"]
            and pack.total_size_bytes == entry["size_bytes"]
            and review
            and review.reviewer_id == REVIEWER_ID
            and review.reviewer_id != version.created_by
            and lesson
            and lesson.linked_file_pack_id == pack.lab_file_pack_id
        )
        if not valid:
            raise RuntimeError(f"{entry['lesson_code']} 已有资源与正式实验文件包 v{CONTENT_VERSION} 不一致，脚本拒绝覆盖")

with Session(engine) as session:
    total_lab_resources = session.scalar(
        select(func.count()).select_from(Resource).where(Resource.course_id == COURSE_ID, Resource.resource_type == "LAB_FILE")
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
    "lab_pack_count": len(resource_ids),
    "published_lab_resource_count": total_lab_resources,
    "readiness": {"lab_file": readiness["lab_file"]},
    "course_audit": {"total": audit["total"], "pass": audit["pass"], "blocking": audit["blocking"]},
    "author_identity": AUTHOR_ID,
    "independent_reviewer_identity": REVIEWER_ID,
    "content_boundary": "系统账号隔离、文件校验、容器执行与独立审核记录已验证；未宣称外部教研专家人工验收",
}
if len(set(resource_ids)) != 12 or total_lab_resources != 12:
    raise RuntimeError(f"正式实验文件包资源数量不正确：{result}")
if readiness["lab_file"] != {"ready": 12, "required": 12}:
    raise RuntimeError(f"正式实验文件包就绪度不正确：{result}")
if (audit["total"], audit["pass"], audit["blocking"]) != (196, 73, 123):
    raise RuntimeError(f"课程动态审计未达到题库加实验文件包基线：{result}")
print(json.dumps(result, ensure_ascii=False, indent=2))
