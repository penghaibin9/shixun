"""在 G8 专属门禁库准备成绩、学情和归档真实事实；不得用于生产库。"""
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.common.models import DomainEventOutbox, FileObject
from app.grading import models as grading
from app.lab_classroom import models as classroom
from app.resources.models import ResourceDeliveryManifest
from app.runtime import models as runtime
from app.teaching import models as teaching

COURSE_ID = "course_g8_gate"
CLASS_ID = "class_g8_gate"
LESSON_ID = "lesson_g8_gate"
RELEASE_ID = "release_g8_gate"
VERSION_ID = "labv_g8_gate"
STUDENTS = ("student_g8_001", "student_g8_002")


def remove_archive_files(files: list[FileObject]) -> None:
    configured_root = os.environ.get("YUEKE_RESOURCE_UPLOAD_DIR")
    if not configured_root:
        return
    root = (Path(configured_root).resolve() / "course_archives").resolve()
    for item in files:
        path = Path(item.object_key).resolve()
        safe = root in path.parents and path.name == item.sha256 and len(path.name) == 64
        if safe and path.is_file():
            path.unlink()


def add_event(session: Session, *, event_id: str, event_type: str, aggregate_type: str,
              aggregate_id: str, occurred_at: datetime, payload: dict) -> None:
    session.add(DomainEventOutbox(
        event_id=event_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor_user_id="service_g8_seed",
        occurred_at=occurred_at,
        payload_json=payload,
        idempotency_key=f"g8:{event_id}",
        published_at=None,
    ))


def main() -> None:
    database_url = os.environ.get("YUEKE_DATABASE_URL", "")
    if not database_url or "g8" not in database_url.lower() or "gate" not in database_url.lower():
        raise RuntimeError("G8 seed 只允许写入名称同时含 g8 和 gate 的专属门禁库")
    engine = create_engine(database_url, pool_pre_ping=True)
    stamp = datetime.utcnow().replace(microsecond=0)
    spec = json.loads((Path(__file__).parents[1] / "backend/app/labs/fixtures/rsa-v1.json").read_text(encoding="utf-8"))
    roster_snapshot = [{"student_id": student_id, "status": "ACTIVE"} for student_id in STUDENTS]
    roster_hash = hashlib.sha256(json.dumps(roster_snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    with Session(engine) as session:
        archive_files = list(session.scalars(select(FileObject).where(FileObject.bucket == "course-archives")))
        for model in (
            grading.CourseArchiveArtifact, grading.CourseArchive, grading.StudentRiskFlag,
            grading.AnalyticsLabSummary, grading.AnalyticsStudentLabSummary,
            grading.AnalyticsSectionSummary, grading.AnalyticsCourseSummary,
            grading.StudentCourseScore, grading.GradebookItem, grading.Gradebook,
            grading.GradeEvent, grading.GradingPolicyItem, grading.GradingPolicy,
            grading.AuditEvent,
        ):
            session.execute(delete(model))
        session.execute(delete(DomainEventOutbox))
        session.execute(delete(FileObject).where(FileObject.bucket == "course-archives"))
        session.commit()
        remove_archive_files(archive_files)

        instance_ids = [f"rti_g8_{index:03d}" for index in range(1, 3)]
        group_ids = [f"rgp_g8_{index:03d}" for index in range(1, 3)]
        request_ids = [f"rrq_g8_{index:03d}" for index in range(1, 3)]
        session.execute(delete(classroom.ClassroomRuntimeEvent).where(classroom.ClassroomRuntimeEvent.lab_release_id == RELEASE_ID))
        session.execute(delete(classroom.RuntimeProjection).where(classroom.RuntimeProjection.lab_release_id == RELEASE_ID))
        session.execute(delete(classroom.ConsumedRuntimeEvent).where(classroom.ConsumedRuntimeEvent.idempotency_key.like("g8:%")))
        session.execute(delete(runtime.CheckpointResult).where(runtime.CheckpointResult.runtime_instance_id.in_(instance_ids)))
        session.execute(delete(runtime.RuntimeEvent).where(runtime.RuntimeEvent.runtime_instance_id.in_(instance_ids)))
        session.execute(delete(runtime.RuntimeInstance).where(runtime.RuntimeInstance.runtime_instance_id.in_(instance_ids)))
        session.execute(delete(runtime.RuntimeInstanceGroup).where(runtime.RuntimeInstanceGroup.runtime_group_id.in_(group_ids)))
        session.execute(delete(runtime.RuntimeRequest).where(runtime.RuntimeRequest.runtime_request_id.in_(request_ids)))
        session.execute(delete(runtime.RuntimeReleaseReadModel).where(runtime.RuntimeReleaseReadModel.lab_release_id == RELEASE_ID))
        session.execute(delete(runtime.InfraNode).where(runtime.InfraNode.node_id == "node_g8_gate"))

        session.execute(delete(teaching.QuizAnswer).where(teaching.QuizAnswer.attempt_id.like("qat_g8_%")))
        session.execute(delete(teaching.QuizAttempt).where(teaching.QuizAttempt.quiz_id == "quiz_g8_gate"))
        session.execute(delete(teaching.QuizQuestionRef).where(teaching.QuizQuestionRef.quiz_id == "quiz_g8_gate"))
        session.execute(delete(teaching.Quiz).where(teaching.Quiz.quiz_id == "quiz_g8_gate"))
        session.execute(delete(teaching.AssignmentSubmission).where(teaching.AssignmentSubmission.assignment_id == "asg_g8_gate"))
        session.execute(delete(teaching.AssignmentQuestionRef).where(teaching.AssignmentQuestionRef.assignment_id == "asg_g8_gate"))
        session.execute(delete(teaching.Assignment).where(teaching.Assignment.assignment_id == "asg_g8_gate"))
        session.execute(delete(teaching.PollAnswer).where(teaching.PollAnswer.poll_id == "poll_g8_gate"))
        session.execute(delete(teaching.PollOption).where(teaching.PollOption.poll_id == "poll_g8_gate"))
        session.execute(delete(teaching.Poll).where(teaching.Poll.poll_id == "poll_g8_gate"))
        session.execute(delete(teaching.AttendanceRecord).where(teaching.AttendanceRecord.task_id == "att_g8_gate"))
        session.execute(delete(teaching.AttendanceTask).where(teaching.AttendanceTask.task_id == "att_g8_gate"))
        session.execute(delete(ResourceDeliveryManifest).where(ResourceDeliveryManifest.course_id == COURSE_ID))
        session.execute(delete(teaching.ClassMembership).where(teaching.ClassMembership.class_id == CLASS_ID))
        session.execute(delete(teaching.TeachingTeacherAssignment).where(teaching.TeachingTeacherAssignment.class_id == CLASS_ID))
        session.execute(delete(teaching.ClassCourse).where(teaching.ClassCourse.class_id == CLASS_ID))
        session.execute(delete(teaching.CourseLesson).where(teaching.CourseLesson.course_id == COURSE_ID))
        session.execute(delete(teaching.CourseChapter).where(teaching.CourseChapter.course_id == COURSE_ID))
        session.execute(delete(teaching.TeachingClass).where(teaching.TeachingClass.class_id == CLASS_ID))
        session.execute(delete(teaching.Course).where(teaching.Course.course_id == COURSE_ID))

        session.add(teaching.Course(course_id=COURSE_ID, name="G8 成绩归档门禁课程", term="2026 秋季", owner_teacher_id="teacher_f", major="网络空间安全", description="成绩到归档真实浏览器验收", status="ACTIVE", created_at=stamp))
        session.add(teaching.TeachingClass(class_id=CLASS_ID, name="G8 验收班", term="2026 秋季", owner_teacher_id="teacher_f", created_at=stamp, roster_frozen_at=stamp, roster_frozen_by="teacher_f", roster_snapshot_hash=roster_hash))
        session.flush()
        session.add(teaching.CourseChapter(chapter_id="chapter_g8_gate", course_id=COURSE_ID, title="综合实验", sequence=1))
        session.flush()
        session.add(teaching.CourseLesson(lesson_id=LESSON_ID, course_id=COURSE_ID, chapter_id="chapter_g8_gate", lesson_code="G8-01", title="RSA 综合实训", sequence=1, lesson_type="LAB"))
        session.add(teaching.ClassCourse(class_course_id="cc_g8_gate", class_id=CLASS_ID, course_id=COURSE_ID))
        session.add(teaching.TeachingTeacherAssignment(assignment_id="tta_g8_gate", teacher_id="teacher_f", class_id=CLASS_ID, course_id=COURSE_ID))
        for index, student_id in enumerate(STUDENTS, 1):
            session.add(teaching.ClassMembership(class_membership_id=f"cm_g8_{index:03d}", class_id=CLASS_ID, student_id=student_id, student_number=f"G8{index:03d}", student_name=f"验收学生{index}", phone=None, email=None, status="ACTIVE", joined_at=stamp))
        session.flush()

        session.add(teaching.AttendanceTask(task_id="att_g8_gate", course_id=COURSE_ID, class_id=CLASS_ID, lesson_id=LESSON_ID, task_type="QR", title="综合实验签到", starts_at=stamp, expires_at=stamp + timedelta(minutes=10), sign_token_hash=hashlib.sha256(b"g8-attendance").hexdigest(), status="CLOSED", created_by="teacher_f"))
        session.add(teaching.Poll(poll_id="poll_g8_gate", course_id=COURSE_ID, class_id=CLASS_ID, lesson_id=LESSON_ID, poll_type="SINGLE", title="课堂互动", status="CLOSED", created_by="teacher_f"))
        session.add(teaching.Assignment(assignment_id="asg_g8_gate", course_id=COURSE_ID, class_id=CLASS_ID, lesson_id=LESSON_ID, title="RSA 课后作业", due_at=stamp + timedelta(days=1), random_order=False, status="PUBLISHED", created_by="teacher_f"))
        session.add(teaching.Quiz(quiz_id="quiz_g8_gate", course_id=COURSE_ID, class_id=CLASS_ID, lesson_id=LESSON_ID, title="RSA 随堂测验", time_limit_minutes=20, random_order=False, status="PUBLISHED", created_by="teacher_f"))
        session.flush()
        session.add(teaching.PollOption(option_id="opt_g8_gate", poll_id="poll_g8_gate", label="已掌握", sequence=1))
        session.flush()

        scores = {
            STUDENTS[0]: {"attendance": (1, 1), "assignment": (80, 100), "quiz": (90, 100), "poll": (1, 1), "lab": (100, 100)},
            STUDENTS[1]: {"attendance": (1, 2), "assignment": (60, 100), "quiz": (70, 100), "poll": (1, 2), "lab": (80, 100)},
        }
        session.add(runtime.InfraNode(node_id="node_g8_gate", name="G8 成绩门禁计算节点", agent_url="http://g8-node.invalid", status="READY", scheduling_paused=False, weight=100, labels_json={"gate":"G8"}, cpu_total=8, memory_total_mb=8192, last_seen_at=stamp, created_at=stamp))
        session.flush()
        session.add(runtime.RuntimeReleaseReadModel(lab_release_id=RELEASE_ID, lab_version_id=VERSION_ID, course_id=COURSE_ID, class_id=CLASS_ID, status="OPEN", spec_snapshot_json=spec, published_at=stamp, updated_at=stamp))
        for index, student_id in enumerate(STUDENTS, 1):
            values = scores[student_id]
            session.add(teaching.AttendanceRecord(record_id=f"atr_g8_{index:03d}", task_id="att_g8_gate", student_id=student_id, signed_at=stamp + timedelta(minutes=1), result="PRESENT" if index == 1 else "LATE", source="QR"))
            session.add(teaching.PollAnswer(answer_id=f"pan_g8_{index:03d}", poll_id="poll_g8_gate", option_id="opt_g8_gate", student_id=student_id, answered_at=stamp + timedelta(minutes=2)))
            session.add(teaching.AssignmentSubmission(submission_id=f"asu_g8_{index:03d}", assignment_id="asg_g8_gate", student_id=student_id, answers_json={"answer": "G8 gate"}, raw_score=values["assignment"][0], max_score=values["assignment"][1], status="GRADED", submitted_at=stamp + timedelta(minutes=3)))
            session.add(teaching.QuizAttempt(attempt_id=f"qat_g8_{index:03d}", quiz_id="quiz_g8_gate", student_id=student_id, status="COMPLETED", started_at=stamp, submitted_at=stamp + timedelta(minutes=4), raw_score=values["quiz"][0], max_score=values["quiz"][1]))
            session.add(runtime.RuntimeRequest(runtime_request_id=request_ids[index-1], lab_release_id=RELEASE_ID, lab_version_id=VERSION_ID, course_id=COURSE_ID, class_id=CLASS_ID, student_id=student_id, mode="STUDENT", status="COMPLETED", requested_by=f"user_{student_id}", idempotency_key=f"g8-runtime-{index}", spec_snapshot_json=spec, error_code=None, error_message=None, submission_status="SUBMITTED", submitted_at=stamp + timedelta(minutes=6), last_activity_at=stamp + timedelta(minutes=6), created_at=stamp, updated_at=stamp + timedelta(minutes=6)))
            session.add(runtime.RuntimeInstanceGroup(runtime_group_id=group_ids[index-1], runtime_request_id=request_ids[index-1], node_id="node_g8_gate", provider_group_id=f"provider_g8_{index}", status="COMPLETED", scheduler_score=100, scheduler_reason="G8 验收运行事实", scheduled_at=stamp, expires_at=stamp + timedelta(hours=1), destroyed_at=None))
            session.add(runtime.RuntimeInstance(runtime_instance_id=instance_ids[index-1], runtime_group_id=group_ids[index-1], student_id=student_id, node_key="student-rsa", role="STUDENT_WORKSTATION", status="COMPLETED", started_at=stamp, expires_at=stamp + timedelta(hours=1), ended_at=stamp + timedelta(minutes=6)))
            session.add(runtime.CheckpointResult(checkpoint_result_id=f"cpr_g8_{index:03d}", runtime_instance_id=instance_ids[index-1], student_id=student_id, checkpoint_id="rsa-fingerprint", attempt=1, status="PASSED", score_awarded=values["lab"][0], max_score=values["lab"][1], evidence_json={"command": "openssl rsa -check", "verified": True}, message="检查点通过", judged_at=stamp + timedelta(minutes=5)))

        manifest_id = "manifest_g8_gate"
        session.add(ResourceDeliveryManifest(resource_delivery_manifest_id=manifest_id, course_id=COURSE_ID, version_no=1, status="FROZEN", manifest_json={"course_id": COURSE_ID, "version_no": 1, "resources": [{"lesson_id": LESSON_ID, "lab_version_id": VERSION_ID}]}, frozen_by="teacher_f", frozen_at=stamp))
        session.flush()

        add_event(session, event_id="evt_g8_roster", event_type="course.roster.frozen", aggregate_type="class", aggregate_id=CLASS_ID, occurred_at=stamp, payload={"course_id": COURSE_ID, "class_id": CLASS_ID, "member_count": len(STUDENTS), "snapshot_hash": roster_hash, "frozen_at": stamp.isoformat() + "Z"})
        add_event(session, event_id="evt_g8_resource", event_type="resource.delivery.frozen", aggregate_type="course", aggregate_id=COURSE_ID, occurred_at=stamp + timedelta(seconds=1), payload={"course_id": COURSE_ID, "manifest_id": manifest_id, "version_no": 1})
        for index, student_id in enumerate(STUDENTS, 1):
            values = scores[student_id]
            common = {"course_id": COURSE_ID, "class_id": CLASS_ID, "lesson_id": LESSON_ID, "student_id": student_id}
            facts = (
                ("attendance.completed", f"evt_g8_att_{index}", f"atr_g8_{index:03d}", "attendance_record", values["attendance"]),
                ("assignment.submitted", f"evt_g8_asg_{index}", f"asu_g8_{index:03d}", "assignment_submission", values["assignment"]),
                ("quiz.completed", f"evt_g8_quiz_{index}", f"qat_g8_{index:03d}", "quiz_attempt", values["quiz"]),
                ("poll.completed", f"evt_g8_poll_{index}", f"pan_g8_{index:03d}", "poll_answer", values["poll"]),
            )
            for offset, (event_type, event_id, source_id, aggregate_type, score) in enumerate(facts, 2):
                add_event(session, event_id=event_id, event_type=event_type, aggregate_type=aggregate_type, aggregate_id=source_id, occurred_at=stamp + timedelta(seconds=index * 10 + offset), payload={**common, "source_id": source_id, "raw_score": score[0], "max_score": score[1]})
            runtime_payload = {**common, "lab_release_id": RELEASE_ID, "runtime_instance_id": instance_ids[index-1], "status": "RUNNING", "current_step": 5, "total_steps": 5, "raw_score": values["lab"][0], "max_score": values["lab"][1]}
            add_event(session, event_id=f"evt_g8_cp_{index}", event_type="lab.checkpoint.passed", aggregate_type="runtime_instance", aggregate_id=instance_ids[index-1], occurred_at=stamp + timedelta(seconds=index * 10 + 6), payload={**runtime_payload, "source_id": f"cpr_g8_{index:03d}", "checkpoint_id": "rsa-fingerprint"})
            add_event(session, event_id=f"evt_g8_lab_{index}", event_type="lab.submitted", aggregate_type="runtime_instance", aggregate_id=instance_ids[index-1], occurred_at=stamp + timedelta(seconds=index * 10 + 7), payload={**runtime_payload, "status": "SUBMITTED", "source_id": request_ids[index-1], "submission_status": "SUBMITTED"})
        session.commit()
    engine.dispose()
    print(json.dumps({"course_id": COURSE_ID, "class_id": CLASS_ID, "lesson_id": LESSON_ID, "students": len(STUDENTS), "outbox_events": 14}, ensure_ascii=False))


if __name__ == "__main__":
    main()
