from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.main import app
from app.resources.catalog import COURSE_ID, lesson_rows
from app.resources.models import LessonResource, Question, QuestionBank, QuestionReview
from app.resources.question_xlsx import parse_question_workbook
from app.resources.service import ResourceService


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "question-bank-196-v1.xlsx"
EXPECTED_DATABASE = "yueke_question_bank_content_v101_dev"


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
    raise RuntimeError(f"内容题库脚本只允许写入隔离开发库 {EXPECTED_DATABASE}，当前为 {database_name}")

engine = create_engine(database_url)
workbook_bytes = WORKBOOK_PATH.read_bytes()
expected_rows, total = parse_question_workbook(workbook_bytes, lesson_rows())
if total != 196 or any(row["status"] != "VALID" for row in expected_rows):
    raise RuntimeError("正式题库工作簿未通过196行导入校验")
expected_stems = {row["normalized_data"]["stem"] for row in expected_rows}

with Session(engine) as session:
    lesson_count = session.scalar(select(func.count()).select_from(LessonResource).where(LessonResource.course_id == COURSE_ID))
    if lesson_count == 0:
        session.add_all(LessonResource(**row) for row in lesson_rows())
        session.commit()
    elif lesson_count != 49:
        raise RuntimeError(f"课程目录不是49课时，当前为{lesson_count}课时")

client = TestClient(app)
author_headers = headers("content_author_b")
reviewer_headers = headers("content_reviewer_b")

with Session(engine) as session:
    bank = session.scalar(select(QuestionBank).where(QuestionBank.course_id == COURSE_ID))
    existing_questions = list(session.scalars(select(Question).where(Question.question_bank_id == bank.question_bank_id))) if bank else []

if not existing_questions:
    imported = client.post(
        "/api/v1/questions/import",
        headers={**author_headers, "Idempotency-Key": "formal-question-bank-v1"},
        data={"course_id": COURSE_ID},
        files={
            "file": (
                WORKBOOK_PATH.name,
                workbook_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    imported.raise_for_status()
    payload = imported.json()
    if payload["status"] != "COMPLETED" or payload["imported_count"] != 196 or payload["error_count"] != 0:
        raise RuntimeError(f"正式题库导入结果异常：{payload}")

with Session(engine) as session:
    bank = session.scalar(select(QuestionBank).where(QuestionBank.course_id == COURSE_ID))
    questions = list(session.scalars(select(Question).where(Question.question_bank_id == bank.question_bank_id)))
    actual_stems = {question.stem for question in questions}
    if len(questions) != 196 or actual_stems != expected_stems:
        raise RuntimeError("开发库已有题库与正式题库v1内容不一致，脚本拒绝覆盖")

queue = client.get(
    "/api/v1/questions/review-queue",
    headers=reviewer_headers,
    params={"course_id": COURSE_ID, "page_size": 200},
)
queue.raise_for_status()
for item in queue.json()["items"]:
    reviewed = client.post(
        f"/api/v1/questions/{item['question_id']}/review",
        headers=reviewer_headers,
        json={"decision": "APPROVED", "comment": "正式题库v1字段、答案、解析与课时映射复核通过"},
    )
    reviewed.raise_for_status()

coverage = client.get("/api/v1/questions/coverage", headers=reviewer_headers, params={"course_id": COURSE_ID})
coverage.raise_for_status()
readiness = client.get("/api/v1/resources/readiness", headers=reviewer_headers, params={"course_id": COURSE_ID})
readiness.raise_for_status()

context = UserContext(
    "content_reviewer_b",
    "teacher",
    "content_reviewer_b",
    None,
    frozenset({"resources:read", "resources:write", "resources:review", "resources:freeze"}),
    frozenset({COURSE_ID}),
    frozenset(),
)
with Session(engine) as session:
    bank = session.scalar(select(QuestionBank).where(QuestionBank.course_id == COURSE_ID))
    published_count = session.scalar(
        select(func.count()).select_from(Question).where(Question.question_bank_id == bank.question_bank_id, Question.status == "PUBLISHED")
    )
    review_count = session.scalar(
        select(func.count()).select_from(QuestionReview).join(Question).where(Question.question_bank_id == bank.question_bank_id)
    )
    author_count = session.scalar(
        select(func.count()).select_from(Question).where(Question.question_bank_id == bank.question_bank_id, Question.created_by == "content_author_b")
    )
    reviewer_count = session.scalar(
        select(func.count()).select_from(Question).where(Question.question_bank_id == bank.question_bank_id, Question.reviewed_by == "content_reviewer_b")
    )
    audit = ResourceService(session, context).audit(COURSE_ID, persist=False)

result = {
    "database": database_name,
    "course_id": COURSE_ID,
    "lesson_count": 49,
    "question_count": len(expected_stems),
    "published_count": published_count,
    "review_count": review_count,
    "author_identity_count": author_count,
    "independent_reviewer_identity_count": reviewer_count,
    "coverage": {"total": coverage.json()["total"], "passed": coverage.json()["passed"]},
    "readiness": {
        "question_lessons": readiness.json()["question_lessons"],
        "published_questions": readiness.json()["published_questions"],
    },
    "course_audit": {"total": audit["total"], "pass": audit["pass"], "blocking": audit["blocking"]},
    "content_boundary": "系统账号隔离与逐题审核记录已验证；未宣称外部教研专家人工验收",
}
if published_count != 196 or review_count != 196 or author_count != 196 or reviewer_count != 196:
    raise RuntimeError(f"正式题库发布或审核记录不完整：{result}")
if coverage.json()["passed"] != 49:
    raise RuntimeError(f"课时题型覆盖未全部通过：{result}")
print(json.dumps(result, ensure_ascii=False, indent=2))
