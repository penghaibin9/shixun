from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from .models import DomainEventOutbox


def enqueue_event(session: Session, *, event_type: str, aggregate_type: str, aggregate_id: str, actor_user_id: str, idempotency_key: str, payload: dict) -> DomainEventOutbox:
    event = DomainEventOutbox(event_id=str(uuid4()), event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, actor_user_id=actor_user_id, occurred_at=datetime.now(timezone.utc), idempotency_key=idempotency_key, payload_json=payload)
    session.add(event)
    return event
