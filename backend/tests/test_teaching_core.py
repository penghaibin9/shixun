from datetime import datetime, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.common.models import Base, DomainEventOutbox
from app.database import get_session
from app.main import app
from app.teaching.models import ClassMembership
from app.teaching.xlsx import HEADERS


@pytest.fixture()
def test_context():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app), sessions
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def headers(*permissions: str, course_id: str = "", class_id: str = "", student_id: str = "", teacher_id: str = "teacher-a"):
    result = {"X-User-Id": student_id or teacher_id, "X-Role": "student" if student_id else "teacher", "X-Permissions": ",".join(permissions)}
    if teacher_id: result["X-Teacher-Id"] = teacher_id
    if student_id: result["X-Student-Id"] = student_id
    if course_id: result["X-Course-Ids"] = course_id
    if class_id: result["X-Class-Ids"] = class_id
    return result


def workbook_bytes(rows):
    book = Workbook(); sheet = book.active; sheet.append(HEADERS)
    for row in rows: sheet.append(row)
    stream = BytesIO(); book.save(stream); return stream.getvalue()


def build_course_class(client: TestClient):
    created = client.post("/api/v1/courses", headers=headers("teaching.course.write"), json={"name": "数据安全技术基础", "term": "2026 秋季", "major": "网络空间安全"})
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]
    created_class = client.post("/api/v1/classes", headers=headers("teaching.class.write", course_id=course_id), json={"name": "网络安全 2301 班", "term": "2026 秋季", "course_id": course_id})
    assert created_class.status_code == 201, created_class.text
    return course_id, created_class.json()["class_id"]


def test_g1_course_class_xlsx_import_idempotency_and_error_rows(test_context):
    client, _ = test_context; course_id, class_id = build_course_class(client)
    scoped = headers("teaching.members.read", "teaching.members.import", course_id=course_id, class_id=class_id)
    template = client.get(f"/api/v1/classes/{class_id}/members/import-template", headers=scoped)
    assert template.status_code == 200
    assert load_workbook(BytesIO(template.content)).active["A1"].value == "学号*"
    rows = [[f"2301{i:03d}", f"学生{i}", "网络安全 2301 班", "", ""] for i in range(1, 44)]
    imported = client.post(f"/api/v1/classes/{class_id}/members/import", headers={**scoped, "Idempotency-Key": "batch-43"}, files={"file": ("students.xlsx", workbook_bytes(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert imported.status_code == 201, imported.text
    assert imported.json()["success_count"] == 43
    replay = client.post(f"/api/v1/classes/{class_id}/members/import", headers={**scoped, "Idempotency-Key": "batch-43"}, files={"file": ("students.xlsx", workbook_bytes(rows))})
    assert replay.json()["job_id"] == imported.json()["job_id"]
    bad = [["2301001", "重复学生", "", "", ""], ["", "无学号", "", "", ""], ["=2+2", "公式风险", "", "", ""]]
    failed = client.post(f"/api/v1/classes/{class_id}/members/import", headers={**scoped, "Idempotency-Key": "bad-batch"}, files={"file": ("bad.xlsx", workbook_bytes(bad))})
    assert failed.json()["failure_count"] == 3
    errors = client.get(f"/api/v1/import-jobs/{failed.json()['job_id']}/error-rows.xlsx", headers=scoped)
    assert errors.status_code == 200 and load_workbook(BytesIO(errors.content)).active.max_row == 4
    members = client.get(f"/api/v1/classes/{class_id}/members", headers=scoped)
    assert members.json()["total"] == 43


def test_g2_attendance_real_sign_duplicate_close_summary_and_scope(test_context):
    client, sessions = test_context; course_id, class_id = build_course_class(client)
    teacher = headers("teaching.members.import", "teaching.members.read", "teaching.attendance.write", "teaching.attendance.read", course_id=course_id, class_id=class_id)
    rows = [["2301001", "张三", "网络安全 2301 班", "", ""]]
    client.post(f"/api/v1/classes/{class_id}/members/import", headers={**teacher, "Idempotency-Key": "one"}, files={"file": ("one.xlsx", workbook_bytes(rows))})
    with sessions() as db: student_id = db.scalar(select(ClassMembership.student_id))
    start, end = datetime.utcnow() - timedelta(minutes=1), datetime.utcnow() + timedelta(minutes=10)
    task = client.post("/api/v1/attendance/tasks", headers=teacher, json={"course_id": course_id, "class_id": class_id, "task_type": "CLASSROOM", "title": "RSA 数字签名课堂签到", "starts_at": start.isoformat(), "expires_at": end.isoformat()})
    assert task.status_code == 201
    published = client.post(f"/api/v1/attendance/tasks/{task.json()['task_id']}/publish", headers=teacher).json()
    student = headers("teaching.attendance.sign", student_id=student_id, teacher_id="", course_id=course_id, class_id=class_id)
    signed = client.post(f"/api/v1/attendance/{task.json()['task_id']}/sign", headers=student, params={"token": published["sign_token"]})
    assert signed.status_code == 200
    with sessions() as db:
        event = db.scalar(select(DomainEventOutbox).where(DomainEventOutbox.event_type == "attendance.completed"))
        assert event.payload_json["raw_score"] == event.payload_json["max_score"] == 1
    duplicate = client.post(f"/api/v1/attendance/{task.json()['task_id']}/sign", headers=student, params={"token": published["sign_token"]})
    assert duplicate.json()["record_id"] == signed.json()["record_id"]
    summary = client.get("/api/v1/attendance/section-summary", headers=teacher).json()["items"][0]
    assert summary | {"expected": 1, "present": 1, "absent": 0} == summary
    client.post(f"/api/v1/attendance/tasks/{task.json()['task_id']}/close", headers=teacher)
    closed = client.post(f"/api/v1/attendance/{task.json()['task_id']}/sign", headers=headers("teaching.attendance.sign", student_id="other", teacher_id="", course_id=course_id, class_id=class_id), params={"token": published["sign_token"]})
    assert closed.status_code in (403, 409)
    outsider = headers("teaching.attendance.read", class_id="class-b", teacher_id="teacher-b")
    assert client.get(f"/api/v1/attendance/tasks/{task.json()['task_id']}", headers=outsider).status_code == 403


@pytest.mark.parametrize("poll_type", ["UNDERSTANDING", "ASSIGNMENT_COMPLETION", "TEACHING_FEEDBACK"])
def test_poll_modes_are_server_aggregated(test_context, poll_type):
    client, sessions = test_context; course_id, class_id = build_course_class(client)
    teacher = headers("teaching.members.import", "teaching.poll.write", "teaching.poll.read", course_id=course_id, class_id=class_id)
    client.post(f"/api/v1/classes/{class_id}/members/import", headers={**teacher, "Idempotency-Key": poll_type}, files={"file": ("one.xlsx", workbook_bytes([["2301001", "张三", "", "", ""]]))})
    with sessions() as db: student_id = db.scalar(select(ClassMembership.student_id))
    poll = client.post("/api/v1/polls", headers=teacher, json={"course_id": course_id, "class_id": class_id, "poll_type": poll_type, "title": "课堂反馈", "options": ["掌握", "需复习"]}).json()
    client.post(f"/api/v1/polls/{poll['poll_id']}/publish", headers=teacher)
    student = headers("teaching.poll.answer", student_id=student_id, teacher_id="", course_id=course_id, class_id=class_id)
    assert client.post(f"/api/v1/polls/{poll['poll_id']}/answers", headers=student, json={"option_id": poll["options"][0]["option_id"]}).status_code == 201
    with sessions() as db:
        event = db.scalar(select(DomainEventOutbox).where(DomainEventOutbox.event_type == "poll.completed"))
        assert event.payload_json["raw_score"] == event.payload_json["max_score"] == 1
    result = client.get(f"/api/v1/polls/{poll['poll_id']}/results", headers=teacher).json()
    assert result["poll_type"] == poll_type and result["items"][0]["count"] == 1


def test_assignment_quiz_events_and_cross_student_isolation(test_context):
    client, sessions = test_context; course_id, class_id = build_course_class(client)
    teacher = headers("teaching.members.import", "teaching.assignment.write", "teaching.quiz.write", course_id=course_id, class_id=class_id)
    client.post(f"/api/v1/classes/{class_id}/members/import", headers={**teacher, "Idempotency-Key": "students"}, files={"file": ("two.xlsx", workbook_bytes([["1", "甲", "", "", ""], ["2", "乙", "", "", ""]]))})
    with sessions() as db: students = list(db.scalars(select(ClassMembership.student_id).order_by(ClassMembership.student_number)))
    due = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    question = {"question_id": "question-b-1", "question_version": "v1", "question_snapshot": {"stem": "公钥用途"}, "max_score": 10}
    assignment = client.post("/api/v1/assignments", headers=teacher, json={"course_id": course_id, "class_id": class_id, "title": "RSA 作业", "due_at": due, "questions": [question]}).json()
    client.post(f"/api/v1/assignments/{assignment['assignment_id']}/publish", headers=teacher)
    student = headers("teaching.assignment.submit", "teaching.quiz.submit", student_id=students[0], teacher_id="", course_id=course_id, class_id=class_id)
    assert client.post(f"/api/v1/assignments/{assignment['assignment_id']}/submit", headers=student, json={"answers": {"question-b-1": "公钥"}, "raw_score": 10, "max_score": 10}).status_code == 201
    quiz = client.post("/api/v1/quizzes", headers=teacher, json={"course_id": course_id, "class_id": class_id, "title": "课堂小测", "time_limit_minutes": 10, "questions": [question]}).json()
    client.post(f"/api/v1/quizzes/{quiz['quiz_id']}/publish", headers=teacher)
    attempt = client.post(f"/api/v1/quizzes/{quiz['quiz_id']}/attempts", headers=student).json()
    other = headers("teaching.quiz.submit", student_id=students[1], teacher_id="", course_id=course_id, class_id=class_id)
    denied = client.post(f"/api/v1/quizzes/{quiz['quiz_id']}/attempts/{attempt['attempt_id']}/submit", headers=other, json={"answers": {}, "raw_score": 0, "max_score": 10})
    assert denied.status_code == 403
    assert client.post(f"/api/v1/quizzes/{quiz['quiz_id']}/attempts/{attempt['attempt_id']}/submit", headers=student, json={"answers": {}, "raw_score": 8, "max_score": 10}).status_code == 200
    with sessions() as db:
        event_types = set(db.scalars(select(DomainEventOutbox.event_type)))
    assert {"assignment.submitted", "quiz.completed", "teaching.audit"} <= event_types


def test_teacher_cannot_access_another_class_and_student_cannot_publish(test_context):
    client, _ = test_context; course_id, class_id = build_course_class(client)
    teacher_b = headers("teaching.members.read", class_id="another-class", teacher_id="teacher-b")
    assert client.get(f"/api/v1/classes/{class_id}/members", headers=teacher_b).status_code == 403
    student = headers("teaching.attendance.sign", student_id="student-a", teacher_id="", class_id=class_id, course_id=course_id)
    body = {"course_id": course_id, "class_id": class_id, "task_type": "CLASSROOM", "title": "越权", "starts_at": datetime.utcnow().isoformat(), "expires_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat()}
    assert client.post("/api/v1/attendance/tasks", headers=student, json=body).status_code == 403


def test_teacher_student_management_search_detail_summary_remove_and_permissions(test_context):
    client, _ = test_context; course_id, class_id = build_course_class(client)
    teacher = headers("teaching.members.read", "teaching.members.write", course_id=course_id, class_id=class_id)
    first = client.post(f"/api/v1/classes/{class_id}/members", headers=teacher, json={"student_id":"existing-student-1","student_number":"2301002","student_name":"李四","email":"li@example.edu.cn"})
    assert first.status_code == 201, first.text
    second = client.post(f"/api/v1/classes/{class_id}/members", headers=teacher, json={"student_id":"existing-student-2","student_number":"2301001","student_name":"张三"})
    assert second.status_code == 201
    listing = client.get(f"/api/v1/classes/{class_id}/members", headers=teacher, params={"search":"张","sort":"student_name","direction":"desc","page":1,"page_size":10}).json()
    assert listing["total"] == 1 and listing["items"][0]["student_name"] == "张三"
    membership_id = first.json()["class_membership_id"]
    assert client.get(f"/api/v1/classes/{class_id}/members/{membership_id}", headers=teacher).json()["email"] == "li@example.edu.cn"
    summary = client.get(f"/api/v1/classes/{class_id}/members/{membership_id}/learning-summary", headers=teacher).json()
    assert summary["experiment"]["label"] == "数据待汇总" and summary["grade"]["label"] == "数据待汇总"
    exported = client.get(f"/api/v1/classes/{class_id}/members/export.xlsx", headers=teacher)
    assert exported.status_code == 200 and load_workbook(BytesIO(exported.content)).active.max_row == 3
    student = headers("teaching.members.read", student_id="existing-student-1", teacher_id="", class_id=class_id, course_id=course_id)
    assert client.delete(f"/api/v1/classes/{class_id}/members/{membership_id}", headers=student).status_code == 403
    other_teacher = headers("teaching.members.read", "teaching.members.write", teacher_id="teacher-b", class_id="class-b")
    assert client.delete(f"/api/v1/classes/{class_id}/members/{membership_id}", headers=other_teacher).status_code == 403
    removed = client.delete(f"/api/v1/classes/{class_id}/members/{membership_id}", headers=teacher)
    assert removed.status_code == 200 and removed.json()["status"] == "REMOVED"
    assert client.get(f"/api/v1/classes/{class_id}/members", headers=teacher).json()["total"] == 1
