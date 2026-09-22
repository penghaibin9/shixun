from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.labs.formal_catalog import COURSE_ID, formal_definition_records
from app.labs.models import LabDefinition, LabVersion
from app.labs.seed import seed_formal_lab_definitions
from app.resources.models import LessonResource


EXPECTED_DATABASE = "yueke_question_bank_content_v101_dev"

database_url = os.environ["YUEKE_DATABASE_URL"]
database_name = make_url(database_url).database
if database_name != EXPECTED_DATABASE:
    raise RuntimeError(f"正式实验定义脚本只允许写入隔离开发库 {EXPECTED_DATABASE}，当前为 {database_name}")

seed_result = seed_formal_lab_definitions()
records = formal_definition_records()
expected_ids = [record["create"].spec.lab_definition_id for record in records]
expected_links = {record["lesson_id"]: record["create"].spec.lab_definition_id for record in records}

engine = create_engine(database_url)
with Session(engine) as session:
    definitions = list(
        session.scalars(
            select(LabDefinition)
            .where(LabDefinition.course_id == COURSE_ID, LabDefinition.lab_definition_id.in_(expected_ids))
            .order_by(LabDefinition.code)
        )
    )
    versions = list(
        session.scalars(
            select(LabVersion).where(
                LabVersion.lab_definition_id.in_(expected_ids),
                LabVersion.version == 1,
                LabVersion.status == "PUBLISHED",
            )
        )
    )
    links = {
        item.lesson_id: item.linked_lab_definition_id
        for item in session.scalars(
            select(LessonResource).where(
                LessonResource.course_id == COURSE_ID,
                LessonResource.lesson_id.in_(expected_links),
            )
        )
    }
    total_course_definitions = session.scalar(
        select(func.count()).select_from(LabDefinition).where(LabDefinition.course_id == COURSE_ID)
    )

engine.dispose()
if len(definitions) != 12 or len(versions) != 12 or links != expected_links:
    raise RuntimeError("正式实验定义、已发布版本或 B/C 课时关联不完整")
if total_course_definitions != 12:
    raise RuntimeError(f"固定课程存在非正式实验定义，拒绝宣称冻结完成：{total_course_definitions}")

print(
    json.dumps(
        {
            "database": database_name,
            "course_id": COURSE_ID,
            "content_version": "1.0.0",
            "formal_definitions": len(definitions),
            "published_v1": len(versions),
            "lesson_links": len(links),
            "seed_result": seed_result,
            "runtime_boundary": "本脚本仅冻结 C 线定义与 B/C 关联；镜像三重验证和容器运行由 D 线门禁负责",
        },
        ensure_ascii=False,
        indent=2,
    )
)
