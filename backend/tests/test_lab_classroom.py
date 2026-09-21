from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.common.models import Base, DomainEventOutbox
from app.database import get_session
from app.lab_classroom.gateway import GatewayBundle, get_gateways
from app.lab_classroom.models import RuntimeProjection
from app.main import app


class FakeClient:
    def __init__(self, domain: str): self.domain = domain
    def request(self, method, path, user, *, params=None, json=None):
        if self.domain == "A": return {"items":[{"student_id":"student-a"},{"student_id":"student-b"}],"total":2}
        if self.domain == "F": return {"grade":{"status":"READY","score":88},"risk":{"status":"READY","level":"LOW"}} if "/grading/students/" in path else {"items":[]}
        if path.endswith("/summary"): return {"lab_release_id":"release-1","class_id":"class-a","course_id":"course-a","started":30,"completed":10,"running":18,"failed":2,"not_started":13}
        if path.endswith("/students"):
            statuses=["SUBMITTED"]*10+["RUNNING"]*18+["FAILED"]*2+["NOT_STARTED"]*13
            return {"items":[{"student_id":f"student-{i+1}","student_name":f"学生{i+1}","status":status,"current_step":3,"total_steps":6,"raw_score":40,"max_score":100,"runtime_instance_id":f"runtime-{i+1}" if status!="NOT_STARTED" else None} for i,status in enumerate(statuses)],"total":43}
        if "/students/" in path: return {"student_id":path.rsplit('/',1)[-1],"class_id":"class-a","status":"RUNNING","runtime_instance_id":"runtime-a","steps":[]}
        if path == "/api/v1/runtime/lab-releases/release-1": return {"lab_release_id":"release-1","class_id":"class-a"}
        if path == "/api/v1/runtime/instances/runtime-a": return {"runtime_instance_id":"runtime-a","class_id":"class-a","student_id":"student-a","status":"RUNNING"}
        if path.endswith("/terminal-token"): return {"token":"short-lived","expires_in":30,"websocket_url":"ws://127.0.0.1:8010/ws/terminal"}
        if path.endswith("/download-url") or path.endswith("/bundle-url"): return {"download_url":"http://127.0.0.1:8010/download/signed","expires_in":60}
        if path.endswith("/logs/traffic") or path == "/api/v1/runtime/logs/traffic": return {"items":[{"artifact_id":"artifact-1","student_id":"student-a","name":"traffic-1.pcap","size_bytes":12},{"artifact_id":"artifact-2","student_id":"student-a","name":"traffic-2.pcap","size_bytes":14}],"total":2}
        if path == "/api/v1/runtime/logs/audit": return {"items":[{"artifact_id":"audit-1","student_id":"student-a","name":"audit.log"}],"total":1}
        if "/log-artifacts/" in path: return {"artifact_id":"artifact-1","class_id":"class-a"}
        return {"status":"ACCEPTED","runtime_instance_id":"runtime-a"}


def fake_gateways(): return GatewayBundle(FakeClient("D"), FakeClient("A"), FakeClient("F"))


@pytest.fixture()
def client_db():
    engine=create_engine("sqlite+pysqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine,expire_on_commit=False)
    def override():
        with sessions() as db: yield db
    app.dependency_overrides[get_session]=override;app.dependency_overrides[get_gateways]=fake_gateways
    yield TestClient(app),sessions
    app.dependency_overrides.clear();Base.metadata.drop_all(engine)


def teacher(*permissions,class_id="class-a"):
    return {"X-User-Id":"teacher-a","X-Role":"teacher","X-Teacher-Id":"teacher-a","X-Permissions":','.join(permissions),"X-Course-Ids":"course-a","X-Class-Ids":class_id}
def student(student_id="student-a",*permissions,class_id="class-a"):
    return {"X-User-Id":student_id,"X-Role":"student","X-Student-Id":student_id,"X-Permissions":','.join(permissions),"X-Course-Ids":"course-a","X-Class-Ids":class_id}


def test_43_student_runtime_summary_and_cross_teacher_scope(client_db):
    client,_=client_db; headers=teacher("classroom.release.read")
    assert client.get("/api/v1/classroom/lab-releases/release-1/summary",headers=headers).json()["started"]==30
    students=client.get("/api/v1/classroom/lab-releases/release-1/students",headers=headers)
    assert students.status_code==200 and students.json()["total"]==43
    assert client.get("/api/v1/classroom/lab-releases/release-1/summary",headers=teacher("classroom.release.read",class_id="class-b")).status_code==403


def test_teacher_high_risk_action_audited_and_student_denied(client_db):
    client,sessions=client_db
    acted=client.post("/api/v1/classroom/runtime/runtime-a/rebuild",headers=teacher("classroom.runtime.rebuild"),json={"reason":"实例异常"})
    assert acted.status_code==200
    with sessions() as db: assert "classroom.audit.requested" in set(db.scalars(select(DomainEventOutbox.event_type)))
    denied=client.post("/api/v1/classroom/runtime/runtime-a/destroy",headers=student("student-a","classroom.lab.read"),json={})
    assert denied.status_code==403
    rebuild_denied=client.post("/api/v1/classroom/runtime/runtime-a/rebuild",headers=student("student-a","classroom.lab.read"),json={})
    assert rebuild_denied.status_code==403
    other_teacher=client.get("/api/v1/classroom/runtime/runtime-a/terminal-token",headers=teacher("classroom.terminal.assist",class_id="class-b"))
    assert other_teacher.status_code==403
    other_token=client.get("/api/v1/classroom/my/runtime/runtime-a/terminal-token",headers=student("student-b","classroom.terminal.use"))
    assert other_token.status_code==403


def test_runtime_event_projection_idempotency_and_learning_read_model(client_db):
    client,sessions=client_db; event={"event_id":"evt-1","event_type":"runtime.status.changed","aggregate_id":"runtime-a","actor_user_id":"system","occurred_at":"2026-09-21T12:00:00","idempotency_key":"runtime-a:v2","payload":{"lab_release_id":"release-1","course_id":"course-a","class_id":"class-a","student_id":"student-a","runtime_instance_id":"runtime-a","status":"RUNNING","current_step":3,"total_steps":6,"raw_score":40,"max_score":100}}
    headers=teacher("classroom.events.consume")
    assert client.post("/api/v1/classroom/events/runtime",headers=headers,json=event).json()["status"]=="CONSUMED"
    assert client.post("/api/v1/classroom/events/runtime",headers=headers,json=event).json()["status"]=="ALREADY_CONSUMED"
    summary=client.get("/api/v1/classroom/read-model/students/student-a/learning-summary?class_id=class-a",headers=teacher("classroom.readmodel.read")).json()
    assert summary["experiment"]["running"]==1 and summary["grade"]["score"]==88
    with sessions() as db: assert db.scalar(select(RuntimeProjection.status))=="RUNNING"


def test_log_distribution_references_artifacts_and_only_target_downloads(client_db):
    client,_=client_db; body={"course_id":"course-a","class_id":"class-a","lab_release_id":"release-1","distribution_type":"TRAFFIC","source_filter":{},"requested_count":2,"target_student_ids":["student-a"],"title":"RSA 流量分析","instruction":"定位异常连接"}
    created=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-1"},json=body)
    assert created.status_code==201 and len(created.json()["items"])==2
    replay=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-1"},json=body)
    assert replay.json()["distribution_id"]==created.json()["distribution_id"]
    assignments=client.get("/api/v1/teaching-logs/my-assignments",headers=student("student-a","classroom.logs.assignment.read")).json()["items"]
    assignment_id=assignments[0]["assignment_id"]
    assert client.get(f"/api/v1/teaching-logs/my-assignments/{assignment_id}/download",headers=student("student-a","classroom.logs.assignment.download")).status_code==200
    assert client.get(f"/api/v1/teaching-logs/my-assignments/{assignment_id}/download",headers=student("student-b","classroom.logs.assignment.download")).status_code==403


def test_missing_runtime_dependency_is_explicit_pending(client_db):
    client,_=client_db; app.dependency_overrides.pop(get_gateways)
    response=client.get("/api/v1/classroom/lab-releases/release-1/summary",headers=teacher("classroom.release.read"))
    assert response.status_code==503 and response.json()["details"]["status"]=="PENDING"
