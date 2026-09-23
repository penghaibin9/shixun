from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


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


# E 课堂线只声明它编排并向浏览器暴露的读取字段；D/F 的原始内部对象不能通过
# 响应模型被无意透传。需要保留的 JSON 证据字段使用 JsonValue，而不是 Any。
class ClassroomReadResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeErrorResponse(ClassroomReadResponseModel):
    code: str
    message: str


class ClassroomRuntimeSchedulerResponse(ClassroomReadResponseModel):
    score: float
    reason: str
    scheduled_at: datetime


class ClassroomRuntimeCheckpointResultResponse(ClassroomReadResponseModel):
    checkpoint_result_id: str
    checkpoint_id: str
    attempt: int
    status: str
    score_awarded: float
    max_score: float
    evidence: dict[str, JsonValue]
    message: str
    judged_at: datetime


class ClassroomRuntimeLogResponse(ClassroomReadResponseModel):
    event_type: str
    actor_user_id: str | None = None
    detail: dict[str, JsonValue] | None = None
    occurred_at: datetime | None = None
    message: str | None = None
    action: str | None = None


class ClassroomRuntimeStepResponse(ClassroomReadResponseModel):
    node_key: str | None = None
    name: str | None = None
    description: str | None = None
    order_no: int | None = None


class ClassroomStudentRuntimeResponse(ClassroomReadResponseModel):
    student_id: str
    student_name: str
    student_no: str
    status: str
    runtime_fact_source: Literal["D_RUNTIME_RELEASE_READ_MODEL"]
    current_step: int | None
    total_steps: int | None
    raw_score: float | None
    max_score: float | None
    runtime_instance_id: str | None
    lab_release_id: str | None = None
    lab_version_id: str | None = None
    course_id: str | None = None
    class_id: str | None = None
    runtime_request_id: str | None = None
    mode: str | None = None
    display_status: str | None = None
    error: RuntimeErrorResponse | None = None
    runtime_group_id: str | None = None
    instance_ids: list[str] | None = None
    submission_status: str | None = None
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    node_key: str | None = None
    role: str | None = None
    node_id: str | None = None
    scheduler: ClassroomRuntimeSchedulerResponse | None = None
    expires_at: datetime | None = None
    network_checks: dict[str, JsonValue] | None = None
    score: float | None = None
    checkpoint_results: list[ClassroomRuntimeCheckpointResultResponse] | None = None
    steps: list[ClassroomRuntimeStepResponse] | None = None
    logs: list[ClassroomRuntimeLogResponse] | None = None


class ClassroomReleaseSummaryResponse(ClassroomReadResponseModel):
    lab_release_id: str
    course_id: str
    class_id: str
    student_count: int
    started: int
    completed: int
    running: int
    failed: int
    not_started: int
    status_counts: dict[str, int]
    runtime_student_count: int
    runtime_fact_source: Literal["D_RUNTIME_RELEASE_READ_MODEL"]
    data_status: Literal["EMPTY", "READY"]
    lab_version_id: str | None = None
    release_status: str | None = None
    running_count: int | None = None
    queued_count: int | None = None
    failed_count: int | None = None
    submitted_count: int | None = None
    updated_at: datetime | None = None


class ClassroomReleaseStudentListResponse(ClassroomReadResponseModel):
    items: list[ClassroomStudentRuntimeResponse]
    page: int
    page_size: int
    total: int
    lab_release_id: str
    course_id: str
    class_id: str
    dependency: Literal["A+D"]
    runtime_fact_source: Literal["D_RUNTIME_RELEASE_READ_MODEL"]
    data_status: Literal["EMPTY", "READY"]


class RuntimeAuditLogItemResponse(ClassroomReadResponseModel):
    event_id: str
    event_type: str
    runtime_instance_id: str | None = None
    lab_release_id: str | None = None
    course_id: str | None = None
    class_id: str | None = None
    student_id: str | None = None
    detail: dict[str, JsonValue] | None = None
    occurred_at: datetime | None = None


class GradingAuditLogItemResponse(ClassroomReadResponseModel):
    audit_event_id: str
    source_event_id: str | None = None
    actor_user_id: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    course_id: str | None = None
    class_id: str | None = None
    student_id: str | None = None
    request_id: str
    ip: str
    result: str
    reason: str | None = None
    occurred_at: datetime
    details: dict[str, JsonValue]


class TeachingAuditLogListResponse(ClassroomReadResponseModel):
    items: list[RuntimeAuditLogItemResponse | GradingAuditLogItemResponse]
    page: int
    page_size: int
    total: int
    dependencies: dict[str, Literal["PENDING", "READY"]]


class TrafficLogItemResponse(ClassroomReadResponseModel):
    artifact_id: str
    name: str
    runtime_instance_id: str | None = None
    lab_release_id: str
    course_id: str
    class_id: str
    student_id: str | None = None
    file_id: str | None = None
    sha256: str | None = None
    size_bytes: int
    occurred_at: datetime | None = None


class TrafficLogListResponse(ClassroomReadResponseModel):
    items: list[TrafficLogItemResponse]
    page: int | None = None
    page_size: int | None = None
    total: int


class TeachingLogDistributionItemResponse(ClassroomReadResponseModel):
    item_id: str
    distribution_id: str
    artifact_id: str
    source_system: str
    source_student_id: str | None = None
    artifact_type: str
    artifact_meta_json: dict[str, JsonValue]


class TeachingLogDistributionResponse(ClassroomReadResponseModel):
    distribution_id: str
    course_id: str
    class_id: str
    lab_release_id: str
    distribution_type: Literal["AUDIT", "TRAFFIC"]
    source_filter_json: dict[str, JsonValue]
    requested_count: int
    title: str
    instruction: str
    due_at: datetime | None = None
    status: str
    idempotency_key: str
    created_by: str
    created_at: datetime
    items: list[TeachingLogDistributionItemResponse] | None = None


class TeachingLogDistributionListResponse(ClassroomReadResponseModel):
    items: list[TeachingLogDistributionResponse]
    page: int
    page_size: int
    total: int


class StudentLogAssignmentResponse(ClassroomReadResponseModel):
    assignment_id: str
    distribution_id: str
    class_id: str
    student_id: str
    status: str
    assigned_at: datetime
    downloaded_at: datetime | None = None
    distribution: TeachingLogDistributionResponse


class StudentLogAssignmentListResponse(ClassroomReadResponseModel):
    items: list[StudentLogAssignmentResponse]
    page: int
    page_size: int
    total: int


class LogDownloadResponse(ClassroomReadResponseModel):
    download_url: str
    artifact_id: str | None = None
    expires_in: int | None = None
    artifact_count: int | None = None
    status: str | None = None


class ClassroomRuntimeEventConsumptionResponse(ClassroomReadResponseModel):
    event_id: str
    status: str


class ClassroomExperimentSummaryResponse(ClassroomReadResponseModel):
    status: Literal["PENDING", "READY"]
    label: str | None = None
    total: int | None = None
    started: int | None = None
    completed: int | None = None
    running: int | None = None
    failed: int | None = None


class ClassroomGradeSummaryResponse(ClassroomReadResponseModel):
    status: str
    label: str | None = None
    score: float | None = None


class ClassroomRiskSummaryResponse(ClassroomReadResponseModel):
    status: str
    label: str | None = None
    level: str | None = None


class ClassroomLearningSummarySourceResponse(ClassroomReadResponseModel):
    experiment: Literal["D_EVENT_PROJECTION"]
    grade_risk: Literal["F_CONTRACT"]


class ClassroomLearningSummaryResponse(ClassroomReadResponseModel):
    student_id: str
    class_id: str
    experiment: ClassroomExperimentSummaryResponse
    grade: ClassroomGradeSummaryResponse
    risk: ClassroomRiskSummaryResponse
    source: ClassroomLearningSummarySourceResponse


class ClassroomReleaseEventResponse(ClassroomReadResponseModel):
    event_sequence: int
    event_id: str
    lab_release_id: str
    student_id: str | None = None
    event_type: str
    payload_json: dict[str, JsonValue]
    occurred_at: datetime
