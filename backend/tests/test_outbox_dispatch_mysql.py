import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox
from app.grading.models import AuditEvent, GradeEvent
from app.lab_classroom.models import RuntimeProjection
from app.main import app
from app.runtime.models import RuntimeReleaseReadModel


pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL 集成库")
SERVICE = {"X-User-Id":"service_contract_dispatcher","X-Role":"admin","X-Permissions":"integration:dispatch"}


def add_event(session: Session, event_type: str, aggregate_id: str, payload: dict) -> str:
    event_id = str(uuid4())
    session.add(DomainEventOutbox(event_id=event_id, event_type=event_type, aggregate_type="integration_test", aggregate_id=aggregate_id, actor_user_id="service_test", occurred_at=datetime.utcnow(), payload_json=payload, idempotency_key=str(uuid4()), published_at=None))
    session.commit()
    return event_id


def test_runtime_events_reach_classroom_and_grading_and_release_reaches_runtime():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    suffix = uuid4().hex[:10]
    course_id, class_id, student_id = f"course_{suffix}", f"class_{suffix}", f"student_{suffix}"
    release_id, instance_id = f"release_{suffix}", f"instance_{suffix}"
    fixture = Path(__file__).parents[1] / "app/labs/fixtures/rsa-v1.json"
    spec = json.loads(fixture.read_text(encoding="utf-8"))
    with Session(engine) as session:
        release_event = add_event(session, "lab.release.published", release_id, {"lab_version_id":f"version_{suffix}","course_id":course_id,"class_id":class_id,"status":"OPEN","spec_snapshot":spec})
        checkpoint_event = add_event(session, "lab.checkpoint.passed", instance_id, {"lab_release_id":release_id,"course_id":course_id,"class_id":class_id,"student_id":student_id,"runtime_instance_id":instance_id,"status":"RUNNING","step":1,"score":20,"source_id":f"checkpoint_{suffix}","raw_score":20,"max_score":20})
        audit_event = add_event(session, "classroom.audit.requested", instance_id, {"action":"runtime.rebuild","course_id":course_id,"class_id":class_id,"student_id":student_id,"reason":"课堂异常处置"})
    client = TestClient(app)
    denied = client.post("/api/v1/integration/outbox/dispatch", headers={"X-User-Id":"teacher_spoof","X-Role":"teacher","X-Permissions":"integration:dispatch"})
    assert denied.status_code == 403 and denied.json()["code"] == "AUTH.INTERNAL_SERVICE_REQUIRED"
    response = client.post("/api/v1/integration/outbox/dispatch", headers=SERVICE, params={"limit":500})
    assert response.status_code == 200, response.text
    selected = {item["event_id"]: item for item in response.json()["results"]}
    assert selected[release_event]["targets"] == ["runtime_release_context"]
    assert selected[checkpoint_event]["targets"] == ["classroom_projection", "grading_facts"]
    assert selected[audit_event]["targets"] == ["audit_event"]
    assert selected[release_event]["status"] == selected[checkpoint_event]["status"] == selected[audit_event]["status"] == "PUBLISHED"
    with Session(engine) as session:
        assert session.get(RuntimeReleaseReadModel, release_id)
        assert session.scalar(select(RuntimeProjection).where(RuntimeProjection.lab_release_id == release_id, RuntimeProjection.student_id == student_id))
        grade = session.scalar(select(GradeEvent).where(GradeEvent.event_id == checkpoint_event))
        assert grade and float(grade.normalized_score) == 100
        audit = session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == audit_event))
        assert audit and audit.action == "runtime.rebuild" and audit.course_id == course_id and audit.class_id == class_id
        assert session.get(DomainEventOutbox, release_event).published_at
        assert session.get(DomainEventOutbox, checkpoint_event).published_at
        assert session.get(DomainEventOutbox, audit_event).published_at
    engine.dispose()
