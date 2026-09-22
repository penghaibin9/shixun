"""在专属门禁库准备 G7 的 43 人真实 MySQL 事实；不得用于生产库。"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox
from app.lab_classroom import models as classroom
from app.runtime import models as runtime
from app.teaching import models as teaching

COURSE_ID = "course_g7_gate"
CLASS_ID = "class_g7_gate"
RELEASE_ID = "release_g7_gate"
VERSION_ID = "labv_g7_gate"
LIVE_EVENT_ID = "evt_g7_live_update"


def main() -> None:
    database_url = os.environ.get("YUEKE_DATABASE_URL", "")
    if not database_url or "gate" not in database_url.lower():
        raise RuntimeError("G7 seed 只允许写入名称含 gate 的专属门禁库")
    engine = create_engine(database_url, pool_pre_ping=True)
    stamp = datetime.utcnow()
    spec = json.loads((Path(__file__).parents[1] / "backend/app/labs/fixtures/rsa-v1.json").read_text(encoding="utf-8"))
    with Session(engine) as session:
        request_ids = [f"rrq_g7_{number:03d}" for number in range(1, 31)]
        group_ids = [f"rgp_g7_{number:03d}" for number in range(1, 31)]
        instance_ids = [f"rti_g7_{number:03d}" for number in range(1, 31)]
        session.execute(delete(DomainEventOutbox).where(DomainEventOutbox.event_id == LIVE_EVENT_ID))
        session.execute(delete(classroom.ClassroomRuntimeEvent).where(classroom.ClassroomRuntimeEvent.lab_release_id == RELEASE_ID))
        session.execute(delete(classroom.RuntimeProjection).where(classroom.RuntimeProjection.lab_release_id == RELEASE_ID))
        session.execute(delete(classroom.ConsumedRuntimeEvent).where(classroom.ConsumedRuntimeEvent.event_id == LIVE_EVENT_ID))
        session.execute(delete(runtime.RuntimeEvent).where(runtime.RuntimeEvent.runtime_instance_id.in_(instance_ids)))
        session.execute(delete(runtime.RuntimeInstance).where(runtime.RuntimeInstance.runtime_instance_id.in_(instance_ids)))
        session.execute(delete(runtime.RuntimeInstanceGroup).where(runtime.RuntimeInstanceGroup.runtime_group_id.in_(group_ids)))
        session.execute(delete(runtime.RuntimeRequest).where(runtime.RuntimeRequest.runtime_request_id.in_(request_ids)))
        session.execute(delete(runtime.RuntimeReleaseReadModel).where(runtime.RuntimeReleaseReadModel.lab_release_id == RELEASE_ID))
        session.execute(delete(runtime.InfraNode).where(runtime.InfraNode.node_id == "node_g7_gate"))
        session.execute(delete(teaching.ClassMembership).where(teaching.ClassMembership.class_id == CLASS_ID))
        session.execute(delete(teaching.TeachingTeacherAssignment).where(teaching.TeachingTeacherAssignment.class_id == CLASS_ID))
        session.execute(delete(teaching.ClassCourse).where(teaching.ClassCourse.class_id == CLASS_ID))
        session.execute(delete(teaching.TeachingClass).where(teaching.TeachingClass.class_id == CLASS_ID))
        session.execute(delete(teaching.Course).where(teaching.Course.course_id == COURSE_ID))

        session.add(teaching.Course(course_id=COURSE_ID, name="G7 真实课堂门禁课程", term="2026 秋季", owner_teacher_id="teacher-user", major="网络空间安全", description="43 人实验课堂验收", status="ACTIVE", created_at=stamp))
        session.add(teaching.TeachingClass(class_id=CLASS_ID, name="网络安全 2301 班", term="2026 秋季", owner_teacher_id="teacher-user", created_at=stamp, roster_frozen_at=stamp, roster_frozen_by="teacher-user", roster_snapshot_hash="g7-gate-snapshot"))
        session.flush()
        session.add(teaching.ClassCourse(class_course_id="cc_g7_gate", class_id=CLASS_ID, course_id=COURSE_ID))
        session.add(teaching.TeachingTeacherAssignment(assignment_id="tta_g7_gate", teacher_id="teacher-user", class_id=CLASS_ID, course_id=COURSE_ID))
        for number in range(1, 44):
            session.add(teaching.ClassMembership(class_membership_id=f"cm_g7_{number:03d}", class_id=CLASS_ID, student_id=f"student_g7_{number:03d}", student_number=f"2026{number:03d}", student_name=f"验收学生{number}", phone=None, email=None, status="ACTIVE", joined_at=stamp))
        session.add(runtime.InfraNode(node_id="node_g7_gate", name="G7 课堂门禁计算节点", agent_url="http://g7-node.invalid", status="READY", scheduling_paused=False, weight=100, labels_json={"gate": "G7"}, cpu_total=64, memory_total_mb=131072, last_seen_at=stamp, created_at=stamp))
        session.flush()
        session.add(runtime.RuntimeReleaseReadModel(lab_release_id=RELEASE_ID, lab_version_id=VERSION_ID, course_id=COURSE_ID, class_id=CLASS_ID, status="OPEN", spec_snapshot_json=spec, published_at=stamp, updated_at=stamp))
        for number in range(1, 31):
            submitted = number <= 10
            failed = number > 28
            request_status = "FAILED" if failed else "RUNNING"
            session.add(runtime.RuntimeRequest(runtime_request_id=request_ids[number-1], lab_release_id=RELEASE_ID, lab_version_id=VERSION_ID, course_id=COURSE_ID, class_id=CLASS_ID, student_id=f"student_g7_{number:03d}", mode="STUDENT", status=request_status, requested_by=f"user_g7_{number:03d}", idempotency_key=f"g7-gate-{number:03d}", spec_snapshot_json=spec, error_code="RUNTIME.GATE_FAILURE" if failed else None, error_message="门禁异常样本" if failed else None, submission_status="SUBMITTED" if submitted else "DRAFT", submitted_at=stamp if submitted else None, last_activity_at=stamp, created_at=stamp, updated_at=stamp))
            session.add(runtime.RuntimeInstanceGroup(runtime_group_id=group_ids[number-1], runtime_request_id=request_ids[number-1], node_id="node_g7_gate", provider_group_id=f"provider_g7_{number:03d}", status=request_status, scheduler_score=100, scheduler_reason="G7 门禁状态事实", scheduled_at=stamp, expires_at=stamp + timedelta(hours=1), destroyed_at=None))
            session.add(runtime.RuntimeInstance(runtime_instance_id=instance_ids[number-1], runtime_group_id=group_ids[number-1], student_id=f"student_g7_{number:03d}", node_key="student-rsa", role="STUDENT_WORKSTATION", status=request_status, started_at=stamp, expires_at=stamp + timedelta(hours=1), ended_at=None))
        session.add(DomainEventOutbox(event_id=LIVE_EVENT_ID, event_type="lab.checkpoint.passed", aggregate_type="runtime_instance", aggregate_id="rti_g7_011", actor_user_id="grader-g7", occurred_at=stamp + timedelta(seconds=1), payload_json={"lab_release_id":RELEASE_ID,"course_id":COURSE_ID,"class_id":CLASS_ID,"student_id":"student_g7_011","runtime_instance_id":"rti_g7_011","status":"RUNNING","current_step":4,"total_steps":5,"raw_score":77,"max_score":100,"source_id":"checkpoint_g7_live","checkpoint_id":"cp_g7_live"}, idempotency_key="g7-live-update", published_at=None))
        session.commit()
    engine.dispose()
    print(json.dumps({"course_id": COURSE_ID, "class_id": CLASS_ID, "release_id": RELEASE_ID, "students": 43, "submitted": 10, "running": 18, "failed": 2, "not_started": 13}, ensure_ascii=False))


if __name__ == "__main__":
    main()
