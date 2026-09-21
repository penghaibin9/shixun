import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox, FileObject
from app.main import app
from app.grading.models import (AnalyticsCourseSummary, AnalyticsLabSummary, AnalyticsSectionSummary, AnalyticsStudentLabSummary,
    AuditEvent, CourseArchive, CourseArchiveArtifact, GradeEvent, Gradebook, GradebookItem, GradingPolicy,
    GradingPolicyItem, StudentCourseScore, StudentRiskFlag)

pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL 集成库")
COURSE, CLASS = "course_data_security", "class_2301"
MANAGER = {"X-User-Id":"teacher_f","X-Role":"teacher","X-Teacher-Id":"teacher_f","X-Course-Ids":COURSE,"X-Class-Ids":CLASS,"X-Permissions":"grading:read,grading:policy,grading:recalculate,grading:post,analytics:class,analytics:read,archives:read,archives:write,archives:freeze,audit:read"}
STUDENT = {"X-User-Id":"user_s1","X-Role":"student","X-Student-Id":"student_1","X-Course-Ids":COURSE,"X-Class-Ids":CLASS,"X-Permissions":"grading:read,analytics:read"}
SERVICE = {"X-User-Id":"service_event_consumer","X-Role":"admin","X-Permissions":"grading:consume,audit:ingest"}
BROWSER_SPOOF = {"X-User-Id":"teacher_f","X-Role":"teacher","X-Teacher-Id":"teacher_f","X-Permissions":"grading:consume,audit:ingest"}


@pytest.fixture(autouse=True)
def clean_database():
    if not os.getenv("YUEKE_DATABASE_URL"): yield; return
    engine=create_engine(os.environ["YUEKE_DATABASE_URL"])
    order=[CourseArchiveArtifact,CourseArchive,StudentRiskFlag,AnalyticsLabSummary,AnalyticsStudentLabSummary,AnalyticsSectionSummary,AnalyticsCourseSummary,StudentCourseScore,GradebookItem,Gradebook,GradeEvent,GradingPolicyItem,GradingPolicy,AuditEvent]
    with Session(engine) as session:
        for model in order: session.execute(delete(model))
        session.execute(delete(DomainEventOutbox));session.execute(delete(FileObject).where(FileObject.storage_provider == "generated-api"));session.commit()
    yield
    with Session(engine) as session:
        for model in order: session.execute(delete(model))
        session.execute(delete(DomainEventOutbox));session.execute(delete(FileObject).where(FileObject.storage_provider == "generated-api"));session.commit()


@pytest.fixture()
def client(): return TestClient(app)


def envelope(event_type, student, source, raw, maximum=100, lesson="lesson_3_2", lab_release_id=None):
    payload={"course_id":COURSE,"class_id":CLASS,"student_id":student,"lesson_id":lesson,"source_id":source,"raw_score":raw,"max_score":maximum}
    if event_type=="lab.submitted":payload["lab_release_id"]=lab_release_id or source
    return {"event_id":str(uuid4()),"event_type":event_type,"aggregate_type":"source_fact","aggregate_id":source,"actor_user_id":"upstream","occurred_at":datetime.now(timezone.utc).isoformat(),"idempotency_key":str(uuid4()),"payload":payload}


def seed_complete_facts(client):
    rows=[]
    for student,scores in {"student_1":[100,80,90,100,70],"student_2":[50,60,70,80,50]}.items():
        for event_type,source,score in zip(["attendance.completed","assignment.submitted","quiz.completed","lab.submitted","poll.completed"],[f"att_{student}",f"ass_{student}",f"quiz_{student}","lab_rsa",f"poll_{student}"],scores):
            data=envelope(event_type,student,source,score);rows.append(data)
            response=client.post("/api/v1/grading/events/consume",headers=SERVICE,json=data);assert response.status_code==200
    return rows


def test_event_replay_three_times_creates_one_grade_event(client):
    data=envelope("quiz.completed","student_1","quiz_once",88)
    assert client.post("/api/v1/grading/events/consume",headers=MANAGER,json=data).status_code==403
    assert client.post("/api/v1/grading/events/consume",headers=BROWSER_SPOOF,json=data).status_code==403
    responses=[client.post("/api/v1/grading/events/consume",headers=SERVICE,json=data).json() for _ in range(3)]
    assert [x["status"] for x in responses]==["CONSUMED","DUPLICATE","DUPLICATE"]
    engine=create_engine(os.environ["YUEKE_DATABASE_URL"])
    with Session(engine) as session: assert len(list(session.query(GradeEvent)))==1


def test_invalid_event_records_one_replayable_error_state(client):
    data=envelope("quiz.completed","student_1","quiz_broken",88);data["payload"].pop("max_score")
    responses=[client.post("/api/v1/grading/events/consume",headers=SERVICE,json=data) for _ in range(3)]
    assert all(x.status_code==422 and x.json()["code"]=="GRADING.EVENT_PAYLOAD_INVALID" for x in responses)
    rows=client.get("/api/v1/audit/events",headers=MANAGER,params={"action":"GRADE_EVENT_REJECTED"}).json()
    assert rows["total"]==1 and rows["items"][0]["result"]=="ERROR"


def test_lab_submission_requires_release_id_and_keeps_source_for_trace(client):
    invalid=envelope("lab.submitted","student_1","submission_without_release",90)
    invalid["payload"].pop("lab_release_id")
    rejected=client.post("/api/v1/grading/events/consume",headers=SERVICE,json=invalid)
    assert rejected.status_code==422 and rejected.json()["details"]["missing"]==["lab_release_id"]
    valid=envelope("lab.submitted","student_1","submission_1",90,lab_release_id="lab_release_rsa")
    assert client.post("/api/v1/grading/events/consume",headers=SERVICE,json=valid).status_code==200
    assert client.post(f"/api/v1/grading/courses/{COURSE}/recalculate",headers=MANAGER,json={"class_id":CLASS}).status_code==200
    labs=client.get(f"/api/v1/analytics/courses/{COURSE}/labs/by-lab",headers=MANAGER,params={"class_id":CLASS}).json()["items"]
    trace=client.get(f"/api/v1/gradebook/courses/{COURSE}/trace/student_1",headers=MANAGER,params={"class_id":CLASS}).json()
    lab_source=next(x for x in trace["components"] if x["component"]=="LAB")["sources"][0]
    assert labs[0]["lab_release_id"]=="lab_release_rsa"
    assert lab_source["source_id"]=="submission_1" and lab_source["lab_release_id"]=="lab_release_rsa"


def test_policy_weight_recalculate_trace_post_analytics_and_student_scope(client):
    bad=client.put(f"/api/v1/grading/policies/{COURSE}",headers=MANAGER,json={"attendance":10,"assignment":20,"quiz":20,"lab":30,"interaction":10})
    assert bad.status_code==422 and bad.json()["code"]=="GRADING.POLICY_WEIGHT_INVALID"
    good=client.put(f"/api/v1/grading/policies/{COURSE}",headers=MANAGER,json={"attendance":10,"assignment":20,"quiz":20,"lab":40,"interaction":10})
    assert good.status_code==200 and sum(x["weight_percent"] for x in good.json()["items"])==100
    seed_complete_facts(client)
    calc=client.post(f"/api/v1/grading/courses/{COURSE}/recalculate",headers=MANAGER,json={"class_id":CLASS})
    assert calc.status_code==200 and calc.json()["status"]=="READY"
    assert client.get(f"/api/v1/gradebook/courses/{COURSE}",headers=MANAGER).status_code==422
    assert client.get(f"/api/v1/gradebook/courses/{COURSE}",headers=MANAGER,params={"class_id":"class_other"}).status_code==403
    book=client.get(f"/api/v1/gradebook/courses/{COURSE}",headers=MANAGER,params={"class_id":CLASS}).json()
    assert [x["total_score"] for x in book["items"]]==[91.0,68.0]
    trace=client.get(f"/api/v1/gradebook/courses/{COURSE}/trace/student_1",headers=MANAGER,params={"class_id":CLASS}).json()
    assert trace["total_score"]==91.0 and len(trace["components"])==5
    overview=client.get(f"/api/v1/analytics/courses/{COURSE}/overview",headers=MANAGER,params={"class_id":CLASS}).json()
    assert overview["avg_assignment"]==70.0 and overview["avg_quiz"]==80.0 and overview["attendance_rate"]==75.0 and overview["course_average"]==79.5
    section=client.get(f"/api/v1/analytics/courses/{COURSE}/sections/lesson_3_2",headers=MANAGER,params={"class_id":CLASS}).json()
    assert section["status"]=="READY" and sum(section["distribution"].values())==2
    labs=client.get(f"/api/v1/analytics/courses/{COURSE}/labs/by-lab",headers=MANAGER,params={"class_id":CLASS}).json()
    assert labs["items"][0]["lab_release_id"]=="lab_rsa" and labs["items"][0]["submitted_students"]==2 and labs["items"][0]["avg_score"]==90.0
    posted=client.post(f"/api/v1/grading/courses/{COURSE}/post",headers=MANAGER,params={"class_id":CLASS})
    assert posted.status_code==200 and posted.json()["status"]=="POSTED"
    own=client.get(f"/api/v1/gradebook/courses/{COURSE}/students/student_1",headers=STUDENT,params={"class_id":CLASS})
    denied=client.get(f"/api/v1/gradebook/courses/{COURSE}/students/student_2",headers=STUDENT,params={"class_id":CLASS})
    assert own.status_code==200 and own.json()["items"][0]["total_score"]==91.0
    assert denied.status_code==403
    assert client.get(f"/api/v1/analytics/courses/{COURSE}/learning-summary",headers=STUDENT,params={"student_id":"student_1"}).status_code==422
    summary=client.get(f"/api/v1/analytics/courses/{COURSE}/learning-summary",headers=STUDENT,params={"class_id":CLASS,"student_id":"student_1"}).json()
    assert summary["status"]=="READY" and summary["grade"]["items"][0]["student_id"]=="student_1"
    assert client.get(f"/api/v1/gradebook/courses/{COURSE}/export.xlsx",headers=MANAGER,params={"class_id":CLASS}).content.startswith(b"PK")
    assert client.get(f"/api/v1/analytics/courses/{COURSE}/export.xlsx",headers=MANAGER,params={"class_id":CLASS}).content.startswith(b"PK")


def test_archive_blocks_until_upstream_facts_then_locks_and_audits(client):
    seed_complete_facts(client)
    client.post(f"/api/v1/grading/courses/{COURSE}/recalculate",headers=MANAGER,json={"class_id":CLASS})
    client.post(f"/api/v1/grading/courses/{COURSE}/post",headers=MANAGER,params={"class_id":CLASS})
    blocked=client.post(f"/api/v1/archives/courses/{COURSE}/precheck",headers=MANAGER,json={"class_id":CLASS}).json()
    assert set(blocked["blocking_items"])=={"roster_frozen","resources_frozen"}
    for event_type,aggregate in [("course.roster.frozen","roster_2301"),("resource.delivery.frozen","resource_manifest_1")]:
        data={"event_id":str(uuid4()),"event_type":event_type,"aggregate_type":"upstream_manifest","aggregate_id":aggregate,"actor_user_id":"upstream","occurred_at":datetime.now(timezone.utc).isoformat(),"idempotency_key":str(uuid4()),"payload":{"course_id":COURSE,"class_id":CLASS}}
        if event_type=="course.roster.frozen":data["payload"]["class_id"]="class_other"
        assert client.post("/api/v1/grading/events/consume",headers=SERVICE,json=data).status_code==200
    wrong_class=client.post(f"/api/v1/archives/courses/{COURSE}/precheck",headers=MANAGER,json={"class_id":CLASS}).json()
    assert wrong_class["blocking_items"]==["roster_frozen"]
    roster={"event_id":str(uuid4()),"event_type":"course.roster.frozen","aggregate_type":"upstream_manifest","aggregate_id":"roster_2301_correct","actor_user_id":"upstream","occurred_at":datetime.now(timezone.utc).isoformat(),"idempotency_key":str(uuid4()),"payload":{"course_id":COURSE,"class_id":CLASS}}
    assert client.post("/api/v1/grading/events/consume",headers=SERVICE,json=roster).status_code==200
    ready=client.post(f"/api/v1/archives/courses/{COURSE}/precheck",headers=MANAGER,json={"class_id":CLASS}).json();assert ready["blocking"]==0
    frozen=client.post(f"/api/v1/archives/courses/{COURSE}/freeze",headers=MANAGER,json={"class_id":CLASS})
    assert frozen.status_code==200 and len(frozen.json()["artifacts"])==3
    assert all(x.get("file_id") for x in frozen.json()["artifacts"][:2])
    engine=create_engine(os.environ["YUEKE_DATABASE_URL"])
    with Session(engine) as session: assert session.query(FileObject).filter(FileObject.storage_provider == "generated-api").count()==2
    locked=client.post(f"/api/v1/grading/courses/{COURSE}/recalculate",headers=MANAGER,json={"class_id":CLASS})
    assert locked.status_code==409 and locked.json()["code"]=="ARCHIVE.GRADEBOOK_LOCKED"
    audits=client.get("/api/v1/audit/events",headers=MANAGER,params={"course_id":COURSE}).json()
    actions={x["action"] for x in audits["items"]}
    assert {"GRADEBOOK_RECALCULATED","GRADEBOOK_POSTED","COURSE_ARCHIVE_PRECHECK","COURSE_ARCHIVED"}<=actions
    assert client.delete("/api/v1/audit/events",headers=MANAGER).status_code==405
    assert client.get("/api/v1/audit/events/export.xlsx",headers=MANAGER).content.startswith(b"PK")
    assert client.get("/api/v1/audit/events/export.csv",headers=MANAGER).content.startswith(b"\xef\xbb\xbf")


def test_cross_domain_high_risk_audit_is_idempotent_and_immutable(client):
    data={"source_event_id":"runtime-destroyed-1","actor_user_id":"admin_d","actor_role":"admin","action":"RUNTIME_INSTANCE_DESTROYED","resource_type":"runtime_instance","resource_id":"instance_1","course_id":COURSE,"class_id":CLASS,"student_id":"student_1","result":"SUCCESS","reason":"教师确认重建","occurred_at":datetime.now(timezone.utc).isoformat(),"details":{"node_id":"node_1"}}
    assert client.post("/api/v1/audit/events/ingest",headers=MANAGER,json=data).status_code==403
    assert client.post("/api/v1/audit/events/ingest",headers=BROWSER_SPOOF,json=data).status_code==403
    results=[client.post("/api/v1/audit/events/ingest",headers=SERVICE,json=data).json()["status"] for _ in range(3)]
    assert results==["RECORDED","DUPLICATE","DUPLICATE"]
    rows=client.get("/api/v1/audit/events",headers=MANAGER,params={"action":"RUNTIME_INSTANCE_DESTROYED"}).json()
    assert rows["total"]==1 and rows["items"][0]["reason"]=="教师确认重建"
    assert client.patch(f"/api/v1/audit/events/{rows['items'][0]['audit_event_id']}",headers=MANAGER,json={"reason":"篡改"}).status_code in {404,405}


def test_risk_flags_are_backed_by_checkpoint_and_submission_facts(client):
    for source in ["checkpoint_1","checkpoint_2"]:
        assert client.post("/api/v1/grading/events/consume",headers=SERVICE,json=envelope("lab.checkpoint.failed","student_1",source,0)).status_code==200
    for source in ["lab_1","lab_2","lab_3"]:
        assert client.post("/api/v1/grading/events/consume",headers=SERVICE,json=envelope("lab.submitted","student_2",f"submission_{source}",80,lab_release_id=source)).status_code==200
    assert client.post(f"/api/v1/grading/courses/{COURSE}/recalculate",headers=MANAGER,json={"class_id":CLASS}).status_code==200
    risks=client.get(f"/api/v1/analytics/courses/{COURSE}/risks",headers=MANAGER,params={"class_id":CLASS,"student_id":"student_1"}).json()["items"]
    by_type={x["risk_type"]:x["evidence"] for x in risks}
    assert by_type["CONSECUTIVE_CHECKPOINT_FAILURES"]["failure_count"]==2
    assert by_type["MULTIPLE_MISSING_SUBMISSIONS"]["missing_count"]==3


def test_learning_summary_is_pending_without_upstream_facts(client):
    result=client.get(f"/api/v1/analytics/courses/{COURSE}/learning-summary",headers=MANAGER,params={"class_id":CLASS}).json()
    assert result["status"]=="PENDING" and result["missing_upstream"]
