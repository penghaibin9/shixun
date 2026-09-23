import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox
from app.grading.models import AuditEvent, GradeEvent, GradeScoreProof
from app.grading.service import SCORE_PROOF_EVENT_TYPE, source_proof_digest
from app.lab_classroom.models import RuntimeProjection
from app.main import app
from app.runtime.models import RuntimeReleaseReadModel


pytestmark = pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要专属 MySQL 集成库")
SERVICE = {"X-User-Id":"service_contract_dispatcher","X-Role":"admin","X-Permissions":"integration:dispatch"}


def add_event(session: Session, event_type: str, aggregate_id: str, payload: dict, *, aggregate_type: str = "integration_test", actor_user_id: str = "service_test", event_id: str | None = None, occurred_at: datetime | None = None) -> str:
    event_id = event_id or str(uuid4())
    session.add(DomainEventOutbox(event_id=event_id, event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, actor_user_id=actor_user_id, occurred_at=occurred_at or datetime.utcnow(), payload_json=payload, idempotency_key=str(uuid4()), published_at=None))
    session.commit()
    return event_id


def evidence_hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def add_frozen_score_pair(session: Session, *, course_id: str, class_id: str, student_id: str, suffix: str) -> tuple[str, str]:
    """插入一个分数先到、证明后到的同批事件，验证 dispatcher 仍先派发服务端证明。"""

    score_event_id, proof_event_id = str(uuid4()), str(uuid4())
    source_fact_id, score_aggregate_id = f"attempt_{suffix}", f"quiz_{suffix}"
    occurred_at = datetime.utcnow()
    score_payload = {
        "course_id": course_id,
        "class_id": class_id,
        "student_id": student_id,
        "lesson_id": f"lesson_{suffix}",
        "source_id": source_fact_id,
        "raw_score": 18,
        "max_score": 20,
        "score_proof_event_id": proof_event_id,
    }
    source_proof = {
        "contract": "grading-score-proof/v1",
        "issuer": "teaching-core",
        "origin": "SERVER_GRADED",
        "evidence_type": "QUIZ_FROZEN_QUESTION_SET",
        "source_event_id": score_event_id,
        "source_fact_id": source_fact_id,
        "frozen_question_count": 1,
        "frozen_question_sha256": evidence_hash(f"frozen:{score_aggregate_id}"),
        "answer_evidence_sha256": evidence_hash(f"answers:{source_fact_id}"),
        "scoring_evidence_sha256": evidence_hash(f"score:{source_fact_id}"),
    }
    source_proof["score_payload_sha256"] = source_proof_digest(
        event_id=score_event_id,
        event_type="quiz.completed",
        aggregate_id=score_aggregate_id,
        payload=score_payload,
        proof=source_proof,
        raw=Decimal("18"),
        maximum=Decimal("20"),
    )
    add_event(
        session,
        "quiz.completed",
        score_aggregate_id,
        score_payload,
        aggregate_type="quiz",
        event_id=score_event_id,
        occurred_at=occurred_at,
    )
    add_event(
        session,
        SCORE_PROOF_EVENT_TYPE,
        source_fact_id,
        {
            "score_event_id": score_event_id,
            "score_event_type": "quiz.completed",
            "score_aggregate_id": score_aggregate_id,
            "source_fact_id": source_fact_id,
            "course_id": course_id,
            "class_id": class_id,
            "student_id": student_id,
            "lesson_id": score_payload["lesson_id"],
            "raw_score": 18,
            "max_score": 20,
            "source_proof": source_proof,
        },
        aggregate_type="quiz_attempt",
        actor_user_id="service_teaching_score_prover",
        event_id=proof_event_id,
        # 证明在时间上晚于成绩：排序的 case 仍必须保证本批先入 F。
        occurred_at=occurred_at + timedelta(seconds=60),
    )
    return proof_event_id, score_event_id


def test_runtime_events_reach_classroom_and_grading_and_release_reaches_runtime():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    suffix = uuid4().hex[:10]
    course_id, class_id, student_id = f"course_{suffix}", f"class_{suffix}", f"student_{suffix}"
    release_id, instance_id = f"release_{suffix}", f"instance_{suffix}"
    fixture = Path(__file__).parents[1] / "app/labs/fixtures/rsa-v1.json"
    spec = json.loads(fixture.read_text(encoding="utf-8"))
    with Session(engine) as session:
        release_event = add_event(session, "lab.release.published", release_id, {"lab_version_id":f"version_{suffix}","course_id":course_id,"class_id":class_id,"status":"OPEN","spec_snapshot":spec})
        checkpoint_event = add_event(session, "lab.checkpoint.passed", instance_id, {"lab_release_id":release_id,"course_id":course_id,"class_id":class_id,"student_id":student_id,"runtime_instance_id":instance_id,"status":"RUNNING","step":1,"score":20,"source_id":f"checkpoint_{suffix}","checkpoint_id":"rsa-fingerprint","checkpoint_status":"PASSED","raw_score":20,"max_score":20}, aggregate_type="runtime_instance")
        audit_event = add_event(session, "classroom.audit.requested", instance_id, {"action":"runtime.rebuild","course_id":course_id,"class_id":class_id,"student_id":student_id,"reason":"课堂异常处置"})
        question_import_event = add_event(session, "question.import.completed", f"import_{suffix}", {"course_id": course_id, "total_rows": 196, "success_count": 196, "failure_count": 0, "actor_role": "teacher"})
        question_review_event = add_event(session, "question.published", f"question_{suffix}", {"course_id": course_id, "lesson_id": f"lesson_{suffix}", "decision": "APPROVED", "actor_role": "teacher"})
    client = TestClient(app)
    denied = client.post("/api/v1/integration/outbox/dispatch", headers={"X-User-Id":"teacher_spoof","X-Role":"teacher","X-Permissions":"integration:dispatch"})
    assert denied.status_code == 403 and denied.json()["code"] == "AUTH.INTERNAL_SERVICE_REQUIRED"
    response = client.post("/api/v1/integration/outbox/dispatch", headers=SERVICE, params={"limit":500})
    assert response.status_code == 200, response.text
    selected = {item["event_id"]: item for item in response.json()["results"]}
    assert selected[release_event]["targets"] == ["runtime_release_context"]
    assert selected[checkpoint_event]["targets"] == ["classroom_projection", "grading_facts"]
    assert selected[audit_event]["targets"] == ["audit_event"]
    assert selected[question_import_event]["targets"] == ["audit_event"]
    assert selected[question_review_event]["targets"] == ["audit_event"]
    assert selected[release_event]["status"] == selected[checkpoint_event]["status"] == selected[audit_event]["status"] == "PUBLISHED"
    with Session(engine) as session:
        assert session.get(RuntimeReleaseReadModel, release_id)
        assert session.scalar(select(RuntimeProjection).where(RuntimeProjection.lab_release_id == release_id, RuntimeProjection.student_id == student_id))
        grade = session.scalar(select(GradeEvent).where(GradeEvent.event_id == checkpoint_event))
        assert grade and float(grade.normalized_score) == 100
        audit = session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == audit_event))
        assert audit and audit.action == "runtime.rebuild" and audit.course_id == course_id and audit.class_id == class_id
        question_import_audit = session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == question_import_event))
        question_review_audit = session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == question_review_event))
        assert question_import_audit and question_import_audit.action == "question.import.completed" and question_import_audit.course_id == course_id
        assert question_review_audit and question_review_audit.action == "question.published" and question_review_audit.course_id == course_id
        assert session.get(DomainEventOutbox, release_event).published_at
        assert session.get(DomainEventOutbox, checkpoint_event).published_at
        assert session.get(DomainEventOutbox, audit_event).published_at
    engine.dispose()


def test_dispatcher_publishes_frozen_score_proof_before_same_batch_score_event():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    suffix = uuid4().hex[:10]
    course_id, class_id, student_id = f"course_{suffix}", f"class_{suffix}", f"student_{suffix}"
    with Session(engine) as session:
        proof_event_id, score_event_id = add_frozen_score_pair(
            session,
            course_id=course_id,
            class_id=class_id,
            student_id=student_id,
            suffix=suffix,
        )

    response = TestClient(app).post("/api/v1/integration/outbox/dispatch", headers=SERVICE, params={"limit": 500})
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    result_ids = [item["event_id"] for item in results]
    selected = {item["event_id"]: item for item in results}
    assert result_ids.index(proof_event_id) < result_ids.index(score_event_id)
    assert selected[proof_event_id] == {
        "event_id": proof_event_id,
        "event_type": SCORE_PROOF_EVENT_TYPE,
        "status": "PUBLISHED",
        "targets": ["grading_facts"],
    }
    assert selected[score_event_id]["status"] == "PUBLISHED"
    assert selected[score_event_id]["targets"] == ["grading_facts"]

    with Session(engine) as session:
        proof = session.get(GradeScoreProof, proof_event_id)
        grade = session.scalar(select(GradeEvent).where(GradeEvent.event_id == score_event_id))
        assert proof and proof.score_event_id == score_event_id
        assert grade and grade.source_verification_status == "VERIFIED_SCORE_PROOF"
        assert session.get(DomainEventOutbox, proof_event_id).published_at
        assert session.get(DomainEventOutbox, score_event_id).published_at
    engine.dispose()


def test_dispatcher_archives_registered_non_fact_events_without_creating_domain_facts():
    """Current auth/C/D/E/F producers have an auditable terminal outbox route."""

    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    suffix = uuid4().hex[:10]
    events = [
        (
            "auth.account.created",
            "auth_user",
            f"user_{suffix}",
            {"user_id": f"user_{suffix}", "role": "student", "status": "ACTIVE"},
        ),
        (
            "lab.definition.created",
            "lab_definition",
            f"definition_{suffix}",
            {"course_id": f"course_{suffix}", "lab_version_id": f"version_{suffix}"},
        ),
        (
            "runtime.artifact.direct_download_authorized",
            "runtime_artifact_bundle",
            f"bundle_{suffix}",
            {"reference_ids": [f"artifact_{suffix}"], "reference_count": 1},
        ),
        (
            "teaching.log.distributed",
            "teaching_log_distribution",
            f"distribution_{suffix}",
            {"course_id": f"course_{suffix}", "class_id": f"class_{suffix}", "lab_release_id": f"release_{suffix}"},
        ),
        (
            "grade.event.created",
            "grade_event",
            f"grade_{suffix}",
            {"course_id": f"course_{suffix}", "class_id": f"class_{suffix}", "student_id": f"student_{suffix}"},
        ),
    ]
    with Session(engine) as session:
        event_ids = [
            add_event(
                session,
                event_type,
                aggregate_id,
                payload,
                aggregate_type=aggregate_type,
            )
            for event_type, aggregate_type, aggregate_id, payload in events
        ]
        unknown_event_id = add_event(
            session,
            "unknown.event",
            f"unknown_{suffix}",
            {"course_id": f"course_{suffix}"},
            aggregate_type="unknown_aggregate",
        )

    response = TestClient(app).post("/api/v1/integration/outbox/dispatch", headers=SERVICE, params={"limit": 500})
    assert response.status_code == 200, response.text
    selected = {item["event_id"]: item for item in response.json()["results"]}
    assert all(selected[event_id] == {
        "event_id": event_id,
        "event_type": event_type,
        "status": "PUBLISHED",
        "targets": ["audit_archive"],
    } for event_id, (event_type, *_rest) in zip(event_ids, events))
    assert selected[unknown_event_id]["status"] == "FAILED"
    assert selected[unknown_event_id]["code"] == "INTEGRATION.EVENT_UNCONSUMED"

    with Session(engine) as session:
        audits = list(session.scalars(select(AuditEvent).where(AuditEvent.source_event_id.in_(event_ids))))
        assert len(audits) == len(events)
        assert {row.action for row in audits} == {"OUTBOX_EVENT_ARCHIVED"}
        assert all(row.actor_user_id == "service_contract_dispatcher" and row.actor_role == "service" for row in audits)
        assert {row.details_json["source_event"]["event_type"] for row in audits} == {event_type for event_type, *_ in events}
        assert all(session.get(DomainEventOutbox, event_id).published_at is not None for event_id in event_ids)
        assert session.get(DomainEventOutbox, unknown_event_id).published_at is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == unknown_event_id)) is None
    engine.dispose()
