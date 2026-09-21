from __future__ import annotations

import os
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox
from app.main import app
from app.resources.models import LessonResource, Resource
from app.teaching.models import Course, CourseChapter, CourseLesson


pytestmark = pytest.mark.skipif(
    not os.getenv("YUEKE_DATABASE_URL"),
    reason="需要专属 MySQL（关系型数据库）集成库",
)


def headers(*permissions: str, course_ids: tuple[str, ...] = ()) -> dict[str, str]:
    return {
        "X-User-Id": "curriculum_authority_teacher",
        "X-Role": "teacher",
        "X-Teacher-Id": "curriculum_authority_teacher",
        "X-Course-Ids": ",".join(course_ids),
        "X-Permissions": ",".join(permissions),
    }


def create_course(client: TestClient, suffix: str) -> str:
    response = client.post(
        "/api/v1/courses",
        headers=headers("teaching.course.write"),
        json={
            "name": f"权威目录回归课程 {suffix}",
            "term": "2026 秋季",
            "major": "网络空间安全",
            "description": "验证 A、B 共用同一课程课时事实",
        },
    )
    assert response.status_code == 201, response.text
    assert (response.json()["theory_lesson_count"], response.json()["lab_lesson_count"]) == (37, 12)
    return response.json()["course_id"]


def test_mysql_curriculum_authority_foreign_key_service_scope_and_b_title_read():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"])
    extension_columns = {column["name"] for column in inspect(engine).get_columns("lesson_resource")}
    assert {"course_id", "lesson_id", "purpose", "environment", "principle", "steps_summary"} <= extension_columns
    assert {"lesson_kind", "chapter_no", "lesson_code", "title"}.isdisjoint(extension_columns)
    client = TestClient(app)
    suffix = uuid4().hex[:8]
    course_ids: list[str] = []

    try:
        first_course = create_course(client, f"A-{suffix}")
        course_ids.append(first_course)
        second_course = create_course(client, f"B-{suffix}")
        course_ids.append(second_course)

        teaching_scope = headers("teaching.course.read", course_ids=(first_course,))
        catalog = client.get(f"/api/v1/courses/{first_course}/lessons", headers=teaching_scope)
        assert catalog.status_code == 200, catalog.text
        assert (catalog.json()["total"], catalog.json()["theory_count"], catalog.json()["lab_count"]) == (49, 37, 12)

        with Session(engine) as session:
            assert session.scalar(
                select(func.count()).select_from(CourseChapter).where(CourseChapter.course_id == first_course)
            ) == 8
            assert session.scalar(
                select(func.count()).select_from(CourseLesson).where(CourseLesson.course_id == first_course)
            ) == 49
            first_lesson = session.scalar(
                select(CourseLesson).where(
                    CourseLesson.course_id == first_course,
                    CourseLesson.lesson_code == "3.2",
                )
            )
            foreign_lesson_id = session.scalar(
                select(CourseLesson.lesson_id).where(
                    CourseLesson.course_id == second_course,
                    CourseLesson.lesson_code == "3.2",
                )
            )
            assert first_lesson is not None and foreign_lesson_id is not None
            assert session.scalar(
                select(LessonResource.lesson_resource_id).where(
                    LessonResource.course_id == first_course,
                    LessonResource.lesson_id == first_lesson.lesson_id,
                )
            ) is None
            first_lesson.title = f"A 模块权威标题 {suffix}"
            first_lesson_id = first_lesson.lesson_id
            authoritative_title = first_lesson.title
            session.commit()

        resource_scope = headers(
            "resources:read",
            "resources:write",
            course_ids=(first_course,),
        )
        theory = client.get(
            "/api/v1/resources/theory-lessons",
            headers=resource_scope,
            params={"course_id": first_course},
        )
        assert theory.status_code == 200, theory.text
        b_lesson = next(item for item in theory.json()["items"] if item["lesson_id"] == first_lesson_id)
        assert b_lesson["title"] == authoritative_title

        denied = client.post(
            "/api/v1/resources",
            headers=resource_scope,
            json={
                "course_id": first_course,
                "lesson_id": foreign_lesson_id,
                "name": "跨课程课时资源",
                "resource_type": "PPT",
            },
        )
        assert denied.status_code == 422, denied.text
        assert denied.json()["code"] == "RESOURCE.LESSON_NOT_FOUND"

        with Session(engine) as session:
            with pytest.raises(IntegrityError):
                session.add(
                    Resource(
                        resource_id=str(uuid4()),
                        course_id=first_course,
                        lesson_id=foreign_lesson_id,
                        name="数据库复合外键拒绝跨课程课时",
                        resource_type="PPT",
                        status="DRAFT",
                        created_by="curriculum_authority_teacher",
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                )
                session.flush()
            session.rollback()
    finally:
        if course_ids:
            with Session(engine) as session:
                session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.aggregate_id.in_(course_ids)))
                session.execute(delete(CourseLesson).where(CourseLesson.course_id.in_(course_ids)))
                session.execute(delete(CourseChapter).where(CourseChapter.course_id.in_(course_ids)))
                session.execute(delete(Course).where(Course.course_id.in_(course_ids)))
                session.commit()
