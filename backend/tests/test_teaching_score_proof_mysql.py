import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox
from app.grading.models import GradeEvent, GradeScoreProof
from app.resources.models import Question, QuestionBank, QuestionLessonMap, QuestionOption
from app.teaching.models import ClassMembership, CourseLesson, TeachingScoreProof
from app.teaching.service import verify_teaching_score_proof
from app.main import app


pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL 集成库")


def teacher_headers(teacher_id: str, *permissions: str, course_id: str = "", class_id: str = "") -> dict[str, str]:
    headers = {
        "X-User-Id": teacher_id,
        "X-Role": "teacher",
        "X-Teacher-Id": teacher_id,
        "X-Permissions": ",".join(permissions),
    }
    if course_id:
        headers["X-Course-Ids"] = course_id
    if class_id:
        headers["X-Class-Ids"] = class_id
    return headers


def student_headers(student_id: str) -> dict[str, str]:
    return {
        "X-User-Id": student_id,
        "X-Role": "student",
        "X-Student-Id": student_id,
        "X-Permissions": "teaching.assignment.submit",
    }


def test_mysql_server_scored_assignment_proof_is_consumed_by_f_before_grade_event():
    """Exercise the real A write path and F dispatcher/consumer in one MySQL database."""

    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    suffix = uuid4().hex[:12]
    teacher_id, student_id = str(uuid4()), str(uuid4())
    client = TestClient(app)

    course_response = client.post(
        "/api/v1/courses",
        headers=teacher_headers(teacher_id, "teaching.course.write"),
        json={"name": f"服务端评分课程 {suffix}", "term": "2026 秋季"},
    )
    assert course_response.status_code == 201, course_response.text
    course_id = course_response.json()["course_id"]
    class_response = client.post(
        "/api/v1/classes",
        headers=teacher_headers(teacher_id, "teaching.class.write", course_id=course_id),
        json={"name": f"服务端评分班 {suffix}", "term": "2026 秋季", "course_id": course_id},
    )
    assert class_response.status_code == 201, class_response.text
    class_id = class_response.json()["class_id"]

    question_id = str(uuid4())
    with Session(engine) as session:
        lesson_id = session.scalar(
            select(CourseLesson.lesson_id)
            .where(CourseLesson.course_id == course_id)
            .order_by(CourseLesson.sequence)
        )
        bank = QuestionBank(
            question_bank_id=str(uuid4()),
            course_id=course_id,
            name="服务端评分题库",
            status="PUBLISHED",
            created_by="resource-author",
            created_at=datetime.utcnow(),
        )
        session.add_all(
            [
                ClassMembership(
                    class_membership_id=str(uuid4()),
                    class_id=class_id,
                    student_id=student_id,
                    student_number=f"S{suffix}",
                    student_name="评分联调学生",
                    phone=None,
                    email=None,
                    status="ACTIVE",
                    joined_at=datetime.utcnow(),
                ),
                bank,
            ]
        )
        session.flush()
        session.add_all(
            [
                Question(
                    question_id=question_id,
                    question_bank_id=bank.question_bank_id,
                    import_job_id=None,
                    source_row_number=None,
                    question_type="SINGLE",
                    stem="服务端冻结题目的正确选项是？",
                    answer_json=["A"],
                    status="PUBLISHED",
                    created_by="resource-author",
                    created_at=datetime.utcnow(),
                    submitted_at=datetime.utcnow(),
                    reviewed_by="resource-reviewer",
                    reviewed_at=datetime.utcnow(),
                ),
                QuestionLessonMap(
                    question_lesson_map_id=str(uuid4()),
                    question_id=question_id,
                    lesson_id=lesson_id,
                ),
                QuestionOption(
                    question_option_id=str(uuid4()),
                    question_id=question_id,
                    option_key="A",
                    option_text="服务端正确答案",
                    is_correct=True,
                ),
                QuestionOption(
                    question_option_id=str(uuid4()),
                    question_id=question_id,
                    option_key="B",
                    option_text="错误答案",
                    is_correct=False,
                ),
            ]
        )
        session.commit()

    teaching = teacher_headers(
        teacher_id,
        "teaching.assignment.write",
        course_id=course_id,
        class_id=class_id,
    )
    assignment_response = client.post(
        "/api/v1/assignments",
        headers=teaching,
        json={
            "course_id": course_id,
            "class_id": class_id,
            "lesson_id": lesson_id,
            "title": "真实 A/F 服务端评分联调",
            "due_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "questions": [{"question_id": question_id}],
        },
    )
    assert assignment_response.status_code == 201, assignment_response.text
    assignment_id = assignment_response.json()["assignment_id"]
    assert client.post(f"/api/v1/assignments/{assignment_id}/publish", headers=teaching).status_code == 200

    submitted = client.post(
        f"/api/v1/assignments/{assignment_id}/submit",
        headers=student_headers(student_id),
        json={"answers": {question_id: "A"}},
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["raw_score"] == submitted.json()["max_score"] == 10

    with Session(engine) as session:
        proof = session.scalar(
            select(TeachingScoreProof).where(TeachingScoreProof.source_fact_id == submitted.json()["submission_id"])
        )
        assert proof
        verify_teaching_score_proof(session, proof.proof_id)
        proof_event = session.get(DomainEventOutbox, proof.score_proof_event_id)
        score_event = session.get(DomainEventOutbox, proof.score_event_id)
        assert proof_event.actor_user_id == "service_teaching_score_prover"
        assert proof_event.occurred_at < score_event.occurred_at
        assert score_event.payload_json["score_proof_event_id"] == proof_event.event_id

    dispatch = client.post(
        "/api/v1/integration/outbox/dispatch",
        headers={
            "X-User-Id": "service_score_proof_dispatcher",
            "X-Role": "admin",
            "X-Permissions": "integration:dispatch",
        },
        params={"limit": 500},
    )
    assert dispatch.status_code == 200, dispatch.text
    results = dispatch.json()["results"]
    result_ids = [item["event_id"] for item in results]
    assert result_ids.index(proof.score_proof_event_id) < result_ids.index(proof.score_event_id)
    result_by_id = {item["event_id"]: item for item in results}
    assert result_by_id[proof.score_proof_event_id]["targets"] == ["grading_facts"]
    assert result_by_id[proof.score_event_id]["targets"] == ["grading_facts"]

    with Session(engine) as session:
        f_proof = session.get(GradeScoreProof, proof.score_proof_event_id)
        grade = session.scalar(select(GradeEvent).where(GradeEvent.event_id == proof.score_event_id))
        assert f_proof and f_proof.score_event_id == proof.score_event_id
        assert grade and grade.source_verification_status == "VERIFIED_SCORE_PROOF"
        assert grade.source_proof_digest == proof.score_payload_sha256
        assert session.get(DomainEventOutbox, proof.score_proof_event_id).published_at
        assert session.get(DomainEventOutbox, proof.score_event_id).published_at
    engine.dispose()
