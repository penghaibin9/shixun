from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RuntimeActionIn(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=240)
    reason: str | None = Field(default=None, max_length=500)


class DistributionCreate(BaseModel):
    course_id: str
    class_id: str
    lab_release_id: str
    distribution_type: Literal["AUDIT", "TRAFFIC"]
    source_filter: dict[str, Any] = Field(default_factory=dict)
    requested_count: int = Field(ge=1, le=1000)
    target_student_ids: list[str] = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=4000)
    due_at: datetime | None = None


class RuntimeEventIn(BaseModel):
    event_id: str
    event_type: Literal["lab.instance.started", "lab.instance.failed", "lab.instance.destroyed", "lab.checkpoint.passed", "lab.checkpoint.failed", "lab.submitted"]
    aggregate_id: str
    actor_user_id: str
    occurred_at: datetime
    idempotency_key: str
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
