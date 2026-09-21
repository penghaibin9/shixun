import os
from datetime import datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text

from app.database import engine
from app.main import app
from app.teaching.xlsx import HEADERS


pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL 集成库")


def identity(*permissions: str, course_id: str = "", class_id: str = "", student_id: str = ""):
    headers = {"X-User-Id": student_id or "mysql-teacher", "X-Role": "student" if student_id else "teacher", "X-Permissions": ",".join(permissions), "X-Course-Ids": course_id, "X-Class-Ids": class_id}
    headers["X-Student-Id" if student_id else "X-Teacher-Id"] = student_id or "mysql-teacher"
    return headers


def xlsx_43() -> bytes:
    book = Workbook(); sheet = book.active; sheet.append(HEADERS)
    run = uuid4().hex[:6]
    for number in range(1, 44): sheet.append([f"{run}{number:03d}", f"验收学生{number}", "网络安全 2301 班", "", ""])
    stream = BytesIO(); book.save(stream); return stream.getvalue()


def test_mysql_84_g1_g2_main_chain():
    assert engine.dialect.name == "mysql"
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "f4e75e84c503"
        assert connection.scalar(text("select version()"))
    client = TestClient(app)
    course = client.post("/api/v1/courses", headers=identity("teaching.course.write"), json={"name":"MySQL 验收课程","term":"2026 秋季"})
    assert course.status_code == 201, course.text
    course_id = course.json()["course_id"]
    teaching = identity("teaching.class.write","teaching.members.import","teaching.members.read","teaching.attendance.write","teaching.attendance.read", course_id=course_id)
    created_class = client.post("/api/v1/classes", headers=teaching, json={"name":"MySQL 验收班","term":"2026 秋季","course_id":course_id})
    assert created_class.status_code == 201, created_class.text
    class_id = created_class.json()["class_id"]; teaching["X-Class-Ids"] = class_id
    imported = client.post(f"/api/v1/classes/{class_id}/members/import", headers={**teaching,"Idempotency-Key":uuid4().hex}, files={"file":("students.xlsx",xlsx_43())})
    assert imported.status_code == 201 and imported.json()["success_count"] == 43
    members = client.get(f"/api/v1/classes/{class_id}/members?page_size=100", headers=teaching).json()
    assert members["total"] == 43
    start, end = datetime.utcnow()-timedelta(minutes=1), datetime.utcnow()+timedelta(minutes=5)
    task = client.post("/api/v1/attendance/tasks", headers=teaching, json={"course_id":course_id,"class_id":class_id,"task_type":"CLASSROOM","title":"真实 MySQL 签到","starts_at":start.isoformat(),"expires_at":end.isoformat()}).json()
    published = client.post(f"/api/v1/attendance/tasks/{task['task_id']}/publish", headers=teaching).json()
    student_id = members["items"][0]["student_id"]
    signed = client.post(f"/api/v1/attendance/{task['task_id']}/sign", headers=identity("teaching.attendance.sign",course_id=course_id,class_id=class_id,student_id=student_id), params={"token":published["sign_token"]})
    assert signed.status_code == 200
    summary = client.get("/api/v1/attendance/section-summary", headers=teaching).json()["items"][0]
    assert summary["expected"] == 43 and summary["present"] == 1
