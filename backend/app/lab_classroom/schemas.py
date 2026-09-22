from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator


EntityId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]


class RuntimeActionIn(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=240)
    reason: str | None = Field(default=None, max_length=500)


class DistributionCreate(BaseModel):
    course_id: str = Field(min_length=1, max_length=36)
    class_id: str = Field(min_length=1, max_length=36)
    lab_release_id: str = Field(min_length=1, max_length=36)
    distribution_type: Literal["AUDIT", "TRAFFIC"]
    source_filter: dict[str, Any] = Field(default_factory=dict)
    requested_count: int = Field(ge=1, le=1000)
    target_student_ids: list[EntityId] = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=4000)
    due_at: datetime | None = None

class RuntimeEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=36)
    event_type: Literal["lab.instance.started", "lab.instance.failed", "lab.instance.destroyed", "lab.checkpoint.passed", "lab.checkpoint.failed", "lab.submitted"]
    aggregate_id: str = Field(min_length=1, max_length=36)
    actor_user_id: str = Field(min_length=1, max_length=36)
    occurred_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_event_type(cls, value):
        if not isinstance(value, dict): return value
        data = dict(value); event_type = data.get("event_type"); payload = data.get("payload") or {}
        direct = {"runtime.started":"lab.instance.started", "checkpoint.passed":"lab.checkpoint.passed", "checkpoint.failed":"lab.checkpoint.failed", "runtime.destroyed":"lab.instance.destroyed"}
        if event_type == "runtime.status.changed":
            event_type = {"RUNNING":"lab.instance.started", "FAILED":"lab.instance.failed", "DESTROYED":"lab.instance.destroyed", "SUBMITTED":"lab.submitted"}.get(payload.get("status"), event_type)
        data["event_type"] = direct.get(event_type, event_type)
        return data
