import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine
from app.lab_classroom.gateway import get_gateways
from app.main import app
from test_lab_classroom import fake_gateways, teacher

pytestmark=pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"),reason="需要专属 MySQL 集成库")


def test_mysql_distribution_and_event_projection():
    assert engine.dialect.name=="mysql"
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version"))
        assert connection.scalar(text("select count(*) from information_schema.tables where table_schema = database() and table_name = 'classroom_runtime_projection'")) == 1
    app.dependency_overrides[get_gateways]=fake_gateways;client=TestClient(app);key=uuid4().hex
    body={"course_id":"course-a","class_id":"class-a","lab_release_id":"release-1","distribution_type":"TRAFFIC","source_filter":{},"requested_count":2,"target_student_ids":["student-a"],"title":"MySQL 日志任务","instruction":"分析流量"}
    created=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":key},json=body)
    assert created.status_code==201,created.text
    event={"event_id":str(uuid4()),"event_type":"lab.instance.started","aggregate_id":"runtime-mysql","actor_user_id":"system","occurred_at":"2026-09-21T12:00:00","idempotency_key":key,"payload":{"lab_release_id":"release-1","course_id":"course-a","class_id":"class-a","student_id":f"student-{key[:6]}","runtime_instance_id":"runtime-mysql","status":"RUNNING","step":0,"score":0}}
    assert client.post("/api/v1/classroom/events/runtime",headers=teacher("classroom.events.consume"),json=event).status_code==200
    app.dependency_overrides.clear()
