from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import DomainEventOutbox
from app.grading.schemas import AuditIngest, EventEnvelope
from app.grading.service import EVENT_TYPES, GradingService
from app.lab_classroom.gateway import get_gateways
from app.lab_classroom.schemas import RuntimeEventIn
from app.lab_classroom.service import ClassroomService
from app.runtime.service import RuntimeService


CLASSROOM_EVENTS = {
    "lab.instance.started",
    "lab.instance.failed",
    "lab.instance.destroyed",
    "lab.checkpoint.passed",
    "lab.checkpoint.failed",
    "lab.submitted",
}
GRADING_EVENTS = set(EVENT_TYPES) | {"resource.delivery.frozen", "course.roster.frozen"}
CLASSROOM_AUDIT_ACTIONS = {
    "runtime.remind",
    "runtime.rejudge",
    "runtime.extend",
    "runtime.unlock",
    "runtime.rebuild",
    "runtime.destroy",
    "release.extend-all",
    "release.remind-idle",
    "terminal.assist.opened",
    "logs.distributed",
}
TEACHING_AUDIT_ACTIONS = {
    "course.created", "course.updated", "class.created",
    "membership.added", "membership.removed", "membership.imported",
    "attendance.created", "attendance.published", "attendance.closed", "attendance.signed",
    "poll.created", "poll.published", "poll.answered",
    "assignment.created", "assignment.published", "assignment.submitted",
    "quiz.created", "quiz.published", "quiz.completed",
}
COURSE_RESOURCE_AUDIT_EVENTS = {
    "resource.created", "resource.version.created", "resource.submit.review",
    "resource.approve", "resource.reject", "resource.publish",
    "resource.audit.completed", "resource.delivery.frozen",
    "question.created", "question.updated", "question.published", "question.rejected",
    "question.import.completed", "question.import.validation_failed",
}


class OutboxDispatcher:
    def __init__(self, session: Session, user: UserContext, request_id: str):
        self.session = session
        self.user = user
        self.request_id = request_id

    def authorize(self) -> None:
        if self.user.role != "admin" or not self.user.user_id.startswith("service_") or "integration:dispatch" not in self.user.permissions:
            raise ApiError("AUTH.INTERNAL_SERVICE_REQUIRED", "该入口仅允许受信任的集成服务调用", 403)

    @staticmethod
    def service_user(event: DomainEventOutbox) -> UserContext:
        payload = event.payload_json or {}
        return UserContext(
            user_id="service_contract_dispatcher",
            role="admin",
            teacher_id=None,
            student_id=None,
            permissions=frozenset({"grading:consume", "audit:ingest", "classroom.events.consume", "runtime.read"}),
            course_ids=frozenset({str(payload["course_id"])}) if payload.get("course_id") else frozenset(),
            class_ids=frozenset({str(payload["class_id"])}) if payload.get("class_id") else frozenset(),
        )

    @staticmethod
    def envelope(event: DomainEventOutbox) -> dict:
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "actor_user_id": event.actor_user_id,
            "occurred_at": event.occurred_at,
            "idempotency_key": event.idempotency_key,
            "payload": event.payload_json or {},
        }

    async def dispatch(self, limit: int = 100) -> dict:
        self.authorize()
        events = list(self.session.scalars(select(DomainEventOutbox).where(DomainEventOutbox.published_at.is_(None)).order_by(DomainEventOutbox.occurred_at, DomainEventOutbox.event_id).limit(limit)))
        results: list[dict] = []
        for event in events:
            targets: list[str] = []
            try:
                context = self.service_user(event)
                envelope = self.envelope(event)
                if event.event_type == "lab.release.published":
                    payload = envelope["payload"]
                    missing = [name for name in ("lab_version_id", "course_id", "class_id", "spec_snapshot") if not payload.get(name)]
                    if missing:
                        raise ApiError("INTEGRATION.RELEASE_PAYLOAD_INVALID", "实验发布事件缺少冻结上下文", 422, {"missing": missing})
                    await RuntimeService(self.session, context).register_release_context(
                        release_id=event.aggregate_id,
                        version_id=payload["lab_version_id"],
                        course_id=payload["course_id"],
                        class_id=payload["class_id"],
                        status=payload.get("status", "OPEN"),
                        spec_snapshot=payload["spec_snapshot"],
                    )
                    targets.append("runtime_release_context")
                if event.event_type in CLASSROOM_EVENTS:
                    classroom_event = RuntimeEventIn.model_validate({key: value for key, value in envelope.items() if key != "aggregate_type"})
                    ClassroomService(self.session, context, get_gateways()).consume_event(classroom_event)
                    targets.append("classroom_projection")
                if event.event_type in GRADING_EVENTS:
                    GradingService(self.session, context, self.request_id, "internal").consume(EventEnvelope.model_validate(envelope))
                    targets.append("grading_facts")
                if event.event_type == "classroom.audit.requested":
                    payload = envelope["payload"]
                    action = payload.get("action")
                    missing = [name for name in ("action", "class_id") if not payload.get(name)]
                    if missing:
                        raise ApiError("INTEGRATION.CLASSROOM_AUDIT_PAYLOAD_INVALID", "课堂审计事件缺少必要字段", 422, {"missing": missing})
                    if action not in CLASSROOM_AUDIT_ACTIONS:
                        raise ApiError("INTEGRATION.CLASSROOM_AUDIT_ACTION_UNSUPPORTED", "课堂审计动作不在允许范围内", 422, {"action": action})
                    resource_type = "lab_release" if action.startswith("release.") else "teaching_log_distribution" if action == "logs.distributed" else "runtime_instance"
                    GradingService(self.session, context, self.request_id, "internal").ingest_audit(AuditIngest(
                        source_event_id=event.event_id,
                        actor_user_id=event.actor_user_id,
                        actor_role=payload.get("actor_role") or "service",
                        action=action,
                        resource_type=resource_type,
                        resource_id=event.aggregate_id,
                        course_id=payload.get("course_id"),
                        class_id=payload["class_id"],
                        student_id=payload.get("student_id"),
                        result="SUCCESS",
                        reason=payload.get("reason"),
                        occurred_at=event.occurred_at,
                        details={"event_type": event.event_type, "payload": payload},
                    ))
                    targets.append("audit_event")
                if event.event_type == "teaching.audit":
                    payload = envelope["payload"]
                    action = payload.get("action")
                    if action not in TEACHING_AUDIT_ACTIONS:
                        raise ApiError("INTEGRATION.TEACHING_AUDIT_ACTION_UNSUPPORTED", "教学审计动作不在允许范围内", 422, {"action": action})
                    GradingService(self.session, context, self.request_id, "internal").ingest_audit(AuditIngest(
                        source_event_id=event.event_id,
                        actor_user_id=event.actor_user_id,
                        actor_role=payload.get("actor_role") or "service",
                        action=action,
                        resource_type=event.aggregate_type,
                        resource_id=event.aggregate_id,
                        course_id=payload.get("course_id"),
                        class_id=payload.get("class_id"),
                        student_id=payload.get("student_id"),
                        result="SUCCESS",
                        occurred_at=event.occurred_at,
                        details={"event_type": event.event_type, "payload": payload},
                    ))
                    targets.append("audit_event")
                if event.event_type in COURSE_RESOURCE_AUDIT_EVENTS:
                    payload = envelope["payload"]
                    GradingService(self.session, context, self.request_id, "internal").ingest_audit(AuditIngest(
                        source_event_id=event.event_id,
                        actor_user_id=event.actor_user_id,
                        actor_role=payload.get("actor_role") or "service",
                        action=event.event_type,
                        resource_type=event.aggregate_type,
                        resource_id=event.aggregate_id,
                        course_id=payload.get("course_id"),
                        class_id=payload.get("class_id"),
                        student_id=payload.get("student_id"),
                        result="SUCCESS",
                        reason=payload.get("comment"),
                        occurred_at=event.occurred_at,
                        details={"event_type": event.event_type, "payload": payload},
                    ))
                    targets.append("audit_event")
                if not targets:
                    raise ApiError("INTEGRATION.EVENT_UNCONSUMED", "事件没有已登记的消费者，已保留待处理", 422, {"event_type": event.event_type})
                event.published_at = datetime.utcnow()
                self.session.add(event)
                self.session.commit()
                results.append({"event_id": event.event_id, "event_type": event.event_type, "status": "PUBLISHED", "targets": targets})
            except ApiError as exc:
                self.session.rollback()
                results.append({"event_id": event.event_id, "event_type": event.event_type, "status": "FAILED", "code": exc.code, "message": exc.message, "targets": targets})
            except Exception:
                self.session.rollback()
                results.append({"event_id": event.event_id, "event_type": event.event_type, "status": "FAILED", "code": "INTEGRATION.DISPATCH_FAILED", "message": "事件投递失败，已保留待重试", "targets": targets})
        return {
            "selected": len(events),
            "published": sum(item["status"] == "PUBLISHED" for item in results),
            "failed": sum(item["status"] == "FAILED" for item in results),
            "results": results,
        }
