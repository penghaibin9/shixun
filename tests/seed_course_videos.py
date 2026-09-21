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
from app.resources.media import probe_local_video
from app.resources.models import LessonResource, Resource, ResourceReview, ResourceVersion, VideoAsset
from app.resources.service import ResourceService
from app.teaching.catalog import COURSE_ID, curriculum_rows
from app.teaching.models import Course, CourseChapter, CourseLesson


ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "course-videos-v1"
INDEX_PATH = VIDEO_DIR / "index.json"
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


database_url = os.environ["YUEKE_DATABASE_URL"]
database_name = make_url(database_url).database
if database_name != EXPECTED_DATABASE:
    raise RuntimeError(f"课程视频脚本只允许写入隔离开发库 {EXPECTED_DATABASE}，当前为 {database_name}")

index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
if (
    index.get("course_id") != COURSE_ID
    or index.get("content_version") != CONTENT_VERSION
    or index.get("complete") is not True
    or index.get("video_count") != 49
    or index.get("theory_count") != 37
    or index.get("lab_count") != 12
    or len(index.get("videos", [])) != 49
):
    raise RuntimeError("课程视频索引不是固定课程的完整正式 v1.0.0 版本")

expected_authority = {
    row["lesson_id"]: (row["lesson_code"], row["lesson_type"], row["title"])
    for row in curriculum_rows(COURSE_ID)["lessons"]
}
if {entry["lesson_id"] for entry in index["videos"]} != set(expected_authority):
    raise RuntimeError("课程视频索引与 A 线权威 49 课时目录不一致")

for entry in index["videos"]:
    expected = expected_authority[entry["lesson_id"]]
    if (entry["lesson_code"], entry["lesson_kind"], entry["title"]) != expected:
        raise RuntimeError(f"课程视频课时映射不一致：{entry['lesson_id']}")
    video_path = VIDEO_DIR / entry["filename"]
    if video_path.stat().st_size != entry["size_bytes"] or file_sha256(video_path) != entry["sha256"]:
        raise RuntimeError(f"课程视频校验值或文件大小不匹配：{entry['filename']}")
    duration, width, height = probe_local_video(str(video_path))
    if (
        abs(duration - entry["duration_seconds"]) > 1
        or width != entry["width"]
        or height != entry["height"]
    ):
        raise RuntimeError(f"课程视频真实媒体信息与索引不一致：{entry['filename']}")
    if entry["lesson_kind"] == "THEORY" and not 2100 <= duration <= 2700:
        raise RuntimeError(f"理论视频不在 35～45 分钟门禁内：{entry['filename']}")
    if entry["lesson_kind"] == "LAB" and duration < 600:
        raise RuntimeError(f"实验视频不足 10 分钟：{entry['filename']}")

engine = create_engine(database_url)
with Session(engine) as session:
    course = session.get(Course, COURSE_ID)
    chapters = list(session.scalars(select(CourseChapter).where(CourseChapter.course_id == COURSE_ID)))
    lessons = list(session.scalars(select(CourseLesson).where(CourseLesson.course_id == COURSE_ID)))
    expected = curriculum_rows(COURSE_ID)
    if course is None:
        raise RuntimeError("A 线权威课程不存在，拒绝由 B 线视频脚本创建课程事实")
    if {(row.sequence, row.title) for row in chapters} != {
        (row["sequence"], row["title"]) for row in expected["chapters"]
    }:
        raise RuntimeError("A 线权威章节目录不完整或与冻结目录不一致")
    actual_lessons = {row.lesson_id: (row.lesson_code, row.lesson_type, row.title) for row in lessons}
    if len(lessons) != 49 or actual_lessons != expected_authority:
        raise RuntimeError("A 线权威课时目录不完整或与冻结目录不一致")

client = TestClient(app)
author_headers = headers(AUTHOR_ID)
reviewer_headers = headers(REVIEWER_ID)
resource_ids: list[str] = []
self_review_denial_verified = False

for entry in index["videos"]:
    expected_name = f"{entry['lesson_code']} {entry['title']} 正式讲解视频 v{CONTENT_VERSION}"
    with Session(engine) as session:
        existing = list(
            session.scalars(
                select(Resource).where(
                    Resource.course_id == COURSE_ID,
                    Resource.lesson_id == entry["lesson_id"],
                    Resource.resource_type == "VIDEO",
                )
            )
        )
    if len(existing) > 1:
        raise RuntimeError(f"{entry['lesson_code']} 已有多个视频资源，脚本拒绝覆盖")

    if existing:
        resource_id = existing[0].resource_id
    else:
        video_path = VIDEO_DIR / entry["filename"]
        with video_path.open("rb") as video_stream:
            uploaded = client.post(
                "/api/v1/resources/files",
                headers=author_headers,
                data={"course_id": COURSE_ID},
                files={"file": (entry["filename"], video_stream, "video/mp4")},
            )
        uploaded.raise_for_status()
        file_data = uploaded.json()

        created = client.post(
            "/api/v1/resources",
            headers=author_headers,
            json={
                "course_id": COURSE_ID,
                "lesson_id": entry["lesson_id"],
                "name": expected_name,
                "resource_type": "VIDEO",
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

        submitted = client.post(f"/api/v1/resources/{resource_id}/submit-review", headers=author_headers)
        submitted.raise_for_status()
        if not self_review_denial_verified:
            self_review = client.post(
                f"/api/v1/resources/{resource_id}/approve",
                headers=author_headers,
                json={"comment": "验证制作者不能审核自己的课程视频"},
            )
            if self_review.status_code != 409 or self_review.json().get("code") != "RESOURCE.REVIEWER_MUST_BE_INDEPENDENT":
                raise RuntimeError(f"课程视频独立审核门禁未生效：{self_review.text}")
            self_review_denial_verified = True

        approved = client.post(
            f"/api/v1/resources/{resource_id}/approve",
            headers=reviewer_headers,
            json={"comment": "正式视频校验值、真实时长、画面尺寸、旁白与字幕复核通过"},
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
        asset = (
            session.scalar(select(VideoAsset).where(VideoAsset.resource_version_id == version.resource_version_id))
            if version
            else None
        )
        review = (
            session.scalar(
                select(ResourceReview).where(
                    ResourceReview.resource_version_id == version.resource_version_id,
                    ResourceReview.decision == "APPROVED",
                )
            )
            if version
            else None
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
            and file_object.size_bytes == entry["size_bytes"]
            and asset
            and abs(asset.duration_seconds - entry["duration_seconds"]) <= 1
            and asset.width == entry["width"]
            and asset.height == entry["height"]
            and asset.probed_at
            and review
            and review.reviewer_id == REVIEWER_ID
            and review.reviewer_id != version.created_by
        )
        if not valid:
            raise RuntimeError(f"{entry['lesson_code']} 已有资源与正式视频 v{CONTENT_VERSION} 不一致，脚本拒绝覆盖")
        if entry["lesson_kind"] == "LAB":
            lesson = session.scalar(
                select(LessonResource).where(
                    LessonResource.course_id == COURSE_ID,
                    LessonResource.lesson_id == entry["lesson_id"],
                )
            )
            if not lesson:
                raise RuntimeError(f"{entry['lesson_code']} 实验介绍不存在，拒绝创建第二套课时事实")
            if lesson.linked_video_resource_id not in {None, resource_id}:
                raise RuntimeError(f"{entry['lesson_code']} 已关联其他视频资源，脚本拒绝覆盖")
            lesson.linked_video_resource_id = resource_id
            session.commit()

with Session(engine) as session:
    total_video_resources = session.scalar(
        select(func.count()).select_from(Resource).where(
            Resource.course_id == COURSE_ID,
            Resource.resource_type == "VIDEO",
        )
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

readiness_response = client.get(
    "/api/v1/resources/readiness",
    headers=reviewer_headers,
    params={"course_id": COURSE_ID},
)
readiness_response.raise_for_status()
readiness = readiness_response.json()

result = {
    "database": database_name,
    "course_id": COURSE_ID,
    "content_version": CONTENT_VERSION,
    "video_count": len(resource_ids),
    "published_video_resource_count": total_video_resources,
    "readiness": {
        "theory_video": readiness["theory_video"],
        "lab_video": readiness["lab_video"],
    },
    "course_audit": {"total": audit["total"], "pass": audit["pass"], "blocking": audit["blocking"]},
    "author_identity": AUTHOR_ID,
    "independent_reviewer_identity": REVIEWER_ID,
    "content_boundary": "系统账号隔离、49 个真实媒体探测和独立审核记录已验证；外部教研专家人工抽检仍需另行留痕",
}
if len(set(resource_ids)) != 49 or total_video_resources != 49:
    raise RuntimeError(f"正式课程视频资源数量不正确：{result}")
if readiness["theory_video"] != {"ready": 37, "required": 37}:
    raise RuntimeError(f"正式理论视频就绪度不正确：{result}")
if readiness["lab_video"] != {"ready": 12, "required": 12}:
    raise RuntimeError(f"正式实验视频就绪度不正确：{result}")
if (audit["total"], audit["pass"], audit["blocking"]) != (196, 196, 0):
    raise RuntimeError(f"课程完整性审计未达到 196/196，请先导入 PPT、题库和实验文件包：{result}")
print(json.dumps(result, ensure_ascii=False, indent=2))
