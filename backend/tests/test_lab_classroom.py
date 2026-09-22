from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.common.context import UserContext
from app.common.models import Base, DomainEventOutbox
from app.database import get_session
from app.lab_classroom.gateway import GatewayBundle, downstream_headers, get_gateways
from app.lab_classroom.models import ConsumedRuntimeEvent, RuntimeProjection
from app.lab_classroom.schemas import RuntimeEventIn
from app.main import app


class FakeClient:
    def __init__(self, domain: str): self.domain = domain
    def request(self, method, path, user, *, params=None, json=None):
        if self.domain == "A":
            student_ids = ["student-a", "student-b", *[f"student-{i}" for i in range(3, 44)]]
            members = [{"student_id":student_id,"student_number":f"2026{i+1:03d}","student_name":f"学生{i+1}","status":"ACTIVE"} for i,student_id in enumerate(student_ids)]
            return {"items":members,"total":len(members),"page":1,"page_size":100}
        if self.domain == "F": return {"grade":{"status":"READY","score":88},"risk":{"status":"READY","level":"LOW"}} if "/grading/students/" in path else {"items":[]}
        if path.endswith("/summary"): return {"lab_release_id":"release-1","class_id":"class-a","course_id":"course-a","student_count":30,"status_counts":{"RUNNING":28,"FAILED":2},"running_count":28,"failed_count":2,"submitted_count":10}
        if path.endswith("/students"):
            statuses=["SUBMITTED"]*10+["RUNNING"]*18+["FAILED"]*2
            student_ids = ["student-a", "student-b", *[f"student-{i}" for i in range(3, 31)]]
            return {"items":[{"student_id":student_ids[i],"status":status,"submission_status":"SUBMITTED" if status=="SUBMITTED" else "DRAFT","current_step":3,"total_steps":6,"raw_score":100 if status=="SUBMITTED" else 40,"max_score":100,"runtime_instance_id":f"runtime-{i+1}"} for i,status in enumerate(statuses)],"total":30}
        if "/students/" in path: return {"student_id":path.rsplit('/',1)[-1],"class_id":"class-a","status":"RUNNING","runtime_instance_id":"runtime-a","steps":[]}
        if path == "/api/v1/runtime/lab-releases/release-1": return {"lab_release_id":"release-1","class_id":"class-a"}
        if path == "/api/v1/runtime/instances/runtime-a": return {"runtime_instance_id":"runtime-a","class_id":"class-a","student_id":"student-a","status":"RUNNING"}
        if path.endswith("/terminal-token"): return {"token":"short-lived","expires_in":30,"websocket_url":"ws://127.0.0.1:8010/ws/terminal"}
        if path.endswith("/download-url") or path.endswith("/bundle-url"): return {"download_url":"http://127.0.0.1:8010/download/signed","expires_in":60}
        if path.endswith("/logs/traffic") or path == "/api/v1/runtime/logs/traffic": return {"items":[{"artifact_id":"artifact-1","student_id":"student-a","name":"traffic-1.pcap","size_bytes":12,"course_id":"course-a","class_id":"class-a","lab_release_id":"release-1"},{"artifact_id":"artifact-2","student_id":"student-a","name":"traffic-2.pcap","size_bytes":14,"course_id":"course-a","class_id":"class-a","lab_release_id":"release-1"}],"total":2}
        if path == "/api/v1/runtime/logs/audit": return {"items":[{"event_id":"audit-1","event_type":"runtime.command","student_id":"student-a","course_id":"course-a","class_id":"class-a","lab_release_id":"release-1"}],"total":1}
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
def runtime_service():
    return {"X-User-Id":"service_contract_dispatcher","X-Role":"admin","X-Permissions":"classroom.events.consume"}


def test_43_student_runtime_summary_and_cross_teacher_scope(client_db):
    client,_=client_db; headers=teacher("classroom.release.read")
    summary=client.get("/api/v1/classroom/lab-releases/release-1/summary",headers=headers).json()
    assert summary["started"]==30 and summary["completed"]==10 and summary["running"]==18 and summary["failed"]==2 and summary["not_started"]==13
    students=client.get("/api/v1/classroom/lab-releases/release-1/students",headers=headers)
    assert students.status_code==200 and students.json()["total"]==43 and students.json()["dependency"]=="A+D"
    assert students.json()["items"][-1]["status"]=="NOT_STARTED" and students.json()["items"][-1]["runtime_instance_id"] is None
    assert students.json()["items"][0]["student_name"]=="学生1" and students.json()["items"][0]["student_no"]=="2026001"
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
    denied=client.post("/api/v1/classroom/events/runtime",headers=teacher("classroom.events.consume"),json=event)
    assert denied.status_code==403 and denied.json()["code"]=="AUTH.INTERNAL_SERVICE_REQUIRED"
    headers=runtime_service()
    assert client.post("/api/v1/classroom/events/runtime",headers=headers,json=event).json()["status"]=="CONSUMED"
    assert client.post("/api/v1/classroom/events/runtime",headers=headers,json=event).json()["status"]=="ALREADY_CONSUMED"
    submitted={**event,"event_id":"evt-2","event_type":"lab.submitted","occurred_at":"2026-09-21T12:05:00","idempotency_key":"runtime-a:submitted","payload":{**event["payload"],"status":"SUBMITTED","current_step":6,"raw_score":100}}
    assert client.post("/api/v1/classroom/events/runtime",headers=headers,json=submitted).json()["status"]=="CONSUMED"
    stale={**event,"event_id":"evt-3","occurred_at":"2026-09-21T12:01:00","idempotency_key":"runtime-a:late-start","payload":{**event["payload"],"current_step":1,"raw_score":20}}
    assert client.post("/api/v1/classroom/events/runtime",headers=headers,json=stale).json()["status"]=="STALE_IGNORED"
    summary=client.get("/api/v1/classroom/read-model/students/student-a/learning-summary?class_id=class-a",headers=teacher("classroom.readmodel.read")).json()
    assert summary["experiment"]["completed"]==1 and summary["grade"]["score"]==88
    with sessions() as db:
        projection=db.scalar(select(RuntimeProjection))
        assert projection.status=="SUBMITTED" and float(projection.raw_score)==100 and projection.current_step==6
        assert set(db.scalars(select(ConsumedRuntimeEvent.event_type)))=={"lab.instance.started","lab.submitted"}


@pytest.mark.parametrize("event_type", ["lab.instance.started", "lab.instance.failed", "lab.instance.destroyed", "lab.checkpoint.passed", "lab.checkpoint.failed", "lab.submitted"])
def test_p0_runtime_event_names_are_accepted(event_type):
    model=RuntimeEventIn(event_id="evt",event_type=event_type,aggregate_id="runtime-a",actor_user_id="system",occurred_at="2026-09-21T12:00:00",idempotency_key="stable",payload={})
    assert model.event_type==event_type


def test_legacy_alert_without_p0_equivalent_is_rejected():
    with pytest.raises(ValueError):
        RuntimeEventIn(event_id="evt",event_type="runtime.alert",aggregate_id="runtime-a",actor_user_id="system",occurred_at="2026-09-21T12:00:00",idempotency_key="stable",payload={})


def test_log_distribution_references_artifacts_and_only_target_downloads(client_db):
    client,_=client_db; body={"course_id":"course-a","class_id":"class-a","lab_release_id":"release-1","distribution_type":"TRAFFIC","source_filter":{},"requested_count":2,"target_student_ids":["student-a"],"title":"RSA 流量分析","instruction":"定位异常连接"}
    created=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-1"},json=body)
    assert created.status_code==201 and len(created.json()["items"])==2
    replay=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-1"},json=body)
    assert replay.json()["distribution_id"]==created.json()["distribution_id"]
    conflict=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-1"},json={**body,"title":"不同任务"})
    assert conflict.status_code==409 and conflict.json()["code"]=="REQUEST.IDEMPOTENCY_CONFLICT"
    assignments=client.get("/api/v1/teaching-logs/my-assignments",headers=student("student-a","classroom.logs.assignment.read")).json()["items"]
    assignment_id=assignments[0]["assignment_id"]
    assert client.get(f"/api/v1/teaching-logs/my-assignments/{assignment_id}/download",headers=student("student-a","classroom.logs.assignment.download")).status_code==200
    assert client.get(f"/api/v1/teaching-logs/my-assignments/{assignment_id}/download",headers=student("student-b","classroom.logs.assignment.download")).status_code==403


def test_distribution_scope_and_duplicate_targets_are_rejected(client_db):
    client,_=client_db
    headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-scope"}
    body={"course_id":"course-wrong","class_id":"class-a","lab_release_id":"release-1","distribution_type":"TRAFFIC","source_filter":{},"requested_count":1,"target_student_ids":["student-a"],"title":"范围检查","instruction":"分析日志"}
    denied=client.post("/api/v1/teaching-logs/distributions",headers=headers,json=body)
    assert denied.status_code==403 and denied.json()["code"]=="AUTH.SCOPE_DENIED", denied.text
    duplicate=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-duplicate"},json={**body,"course_id":"course-a","target_student_ids":["student-a","student-a"]})
    assert duplicate.status_code==422 and duplicate.json()["code"]=="LOG_DISTRIBUTION.DUPLICATE_TARGET"


def test_audit_distribution_references_runtime_event_without_copying_log(client_db):
    client,_=client_db
    body={"course_id":"course-a","class_id":"class-a","lab_release_id":"release-1","distribution_type":"AUDIT","source_filter":{},"requested_count":1,"target_student_ids":["student-a"],"title":"审计分析","instruction":"分析操作事件"}
    created=client.post("/api/v1/teaching-logs/distributions",headers={**teacher("classroom.logs.distribute"),"Idempotency-Key":"dist-audit"},json=body)
    assert created.status_code==201
    assert created.json()["items"][0]["artifact_id"]=="audit-1"
    assert created.json()["items"][0]["artifact_meta_json"]["event_type"]=="runtime.command"


def test_log_query_requires_explicit_release_scope(client_db):
    client,_=client_db
    headers=teacher("classroom.logs.read")
    missing=client.get("/api/v1/teaching-logs/traffic",headers=headers)
    assert missing.status_code==422 and missing.json()["code"]=="LOG_QUERY.SCOPE_REQUIRED"
    allowed=client.get("/api/v1/teaching-logs/traffic?class_id=class-a&lab_release_id=release-1",headers=headers)
    assert allowed.status_code==200 and allowed.json()["total"]==2
    denied=client.get("/api/v1/teaching-logs/traffic?class_id=class-b&lab_release_id=release-1",headers=headers)
    assert denied.status_code==403


def test_downstream_permissions_are_minimal_and_cover_real_d_contract():
    user=UserContext(user_id="student-a",role="student",teacher_id=None,student_id="student-a",permissions=frozenset({"classroom.lab.start","classroom.terminal.use"}),course_ids=frozenset({"course-a"}),class_ids=frozenset({"class-a"}))
    permissions=set(downstream_headers(user)["X-Permissions"].split(","))
    assert {"runtime.start","runtime.read","runtime.terminal","teaching.members.read"} <= permissions
    assert "runtime.destroy" not in permissions and "infrastructure.write" not in permissions


def test_missing_runtime_dependency_is_explicit_pending(client_db):
    client,_=client_db; app.dependency_overrides.pop(get_gateways)
    response=client.get("/api/v1/classroom/lab-releases/release-1/summary",headers=teacher("classroom.release.read"))
    assert response.status_code==503 and response.json()["details"]["status"]=="PENDING"
