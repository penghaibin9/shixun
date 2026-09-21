from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    event_type: Literal["runtime.started", "runtime.status.changed", "checkpoint.passed", "checkpoint.failed", "runtime.alert", "lab.submitted", "runtime.destroyed"]
    aggregate_id: str
    actor_user_id: str
    occurred_at: datetime
    idempotency_key: str
    payload: dict[str, Any]
