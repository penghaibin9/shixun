from datetime import datetime
from pydantic import BaseModel, Field


class PolicyInput(BaseModel):
    attendance: float = Field(ge=0, le=100)
    assignment: float = Field(ge=0, le=100)
    quiz: float = Field(ge=0, le=100)
    lab: float = Field(ge=0, le=100)
    interaction: float = Field(ge=0, le=100)
    effective_at: datetime | None = None


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    actor_user_id: str
    occurred_at: datetime
    idempotency_key: str
    payload: dict = Field(
        description=(
            "冻结上游载荷。作业和测验必须引用已由 grading.score.proof.frozen "
            "持久化的 score_proof_event_id；证明事件的 actor_user_id 固定为 "
            "service_teaching_score_prover，自带摘要不能替代受控服务端证明。"
        )
    )


class RecalculateInput(BaseModel):
    class_id: str


class ArchiveInput(BaseModel):
    class_id: str


class AuditIngest(BaseModel):
    source_event_id: str
    actor_user_id: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    course_id: str | None = None
    class_id: str | None = None
    student_id: str | None = None
    result: str = "SUCCESS"
    reason: str | None = None
    occurred_at: datetime
    details: dict = Field(default_factory=dict)
