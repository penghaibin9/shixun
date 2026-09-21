import asyncio
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.models import Base, DomainEventOutbox
from app.grading.models import AuditEvent
from app.integration.service import OutboxDispatcher


SERVICE_USER = UserContext(
    user_id="service_contract_dispatcher",
    role="admin",
    teacher_id=None,
    student_id=None,
    permissions=frozenset({"integration:dispatch"}),
    course_ids=frozenset(),
    class_ids=frozenset(),
)


def add_event(session: Session, event_id: str, action: str, *, event_type: str = "classroom.audit.requested") -> DomainEventOutbox:
    event = DomainEventOutbox(
        event_id=event_id,
        event_type=event_type,
        aggregate_type="classroom_action",
        aggregate_id="runtime-1",
        actor_user_id="teacher-1",
        occurred_at=datetime(2026, 9, 21, 12, 0, 0),
        payload_json={
            "action": action,
            "actor_role": "teacher",
            "course_id": "course-1",
            "class_id": "class-1",
            "student_id": "student-1",
            "reason": "课堂异常处置",
        },
        idempotency_key=f"{action}:runtime-1",
        published_at=None,
    )
    session.add(event)
    session.commit()
    return event


def dispatch(session: Session) -> dict:
    return asyncio.run(OutboxDispatcher(session, SERVICE_USER, "request-1").dispatch(100))


def test_classroom_audit_actions_reach_immutable_audit_idempotently(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'audit.sqlite'}")
    Base.metadata.create_all(engine)
    actions = [
        "runtime.remind",
        "runtime.rejudge",
        "runtime.extend",
        "runtime.unlock",
        "runtime.rebuild",
        "runtime.destroy",
        "release.extend-all",
        "release.remind-idle",
        "terminal.assist.opened",
    ]
    with Session(engine) as session:
        for index, action in enumerate(actions):
            event = add_event(session, f"event-{index}", action)
            if action.startswith("release."):
                event.aggregate_id = "release-1"
                session.commit()

        result = dispatch(session)
        assert result["published"] == len(actions)
        assert result["failed"] == 0
        assert all(item["targets"] == ["audit_event"] for item in result["results"])

        rows = list(session.scalars(select(AuditEvent).order_by(AuditEvent.source_event_id)))
        assert len(rows) == len(actions)
        assert {row.action for row in rows} == set(actions)
        assert all(row.actor_role == "teacher" and row.result == "SUCCESS" for row in rows)
        assert all(row.class_id == "class-1" and row.student_id == "student-1" for row in rows)

        first = session.get(DomainEventOutbox, "event-0")
        first.published_at = None
        session.commit()
        replay = dispatch(session)
        assert replay["published"] == 1 and replay["failed"] == 0
        assert session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == "event-0"))
        assert len(list(session.scalars(select(AuditEvent)))) == len(actions)
    engine.dispose()


def test_failed_or_unconsumed_event_stays_pending_and_can_retry(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retry.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        invalid = add_event(session, "event-invalid", "runtime.not-allowed")
        unknown = add_event(session, "event-unknown", "unused", event_type="unknown.event")

        failed = dispatch(session)
        assert failed["published"] == 0 and failed["failed"] == 2
        assert {item["code"] for item in failed["results"]} == {
            "INTEGRATION.CLASSROOM_AUDIT_ACTION_UNSUPPORTED",
            "INTEGRATION.EVENT_UNCONSUMED",
        }
        assert session.get(DomainEventOutbox, invalid.event_id).published_at is None
        assert session.get(DomainEventOutbox, unknown.event_id).published_at is None
        assert session.scalar(select(AuditEvent)) is None

        invalid.payload_json = {**invalid.payload_json, "action": "runtime.rebuild"}
        session.delete(unknown)
        session.commit()
        retried = dispatch(session)
        assert retried["published"] == 1 and retried["failed"] == 0
        assert session.get(DomainEventOutbox, invalid.event_id).published_at is not None
        assert session.scalar(select(AuditEvent).where(AuditEvent.source_event_id == invalid.event_id)).action == "runtime.rebuild"
    engine.dispose()
