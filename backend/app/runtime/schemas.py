from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStart(StrictModel):
    lab_release_id: str = Field(min_length=1, max_length=36)
    lab_version_id: str = Field(min_length=1, max_length=36)
    course_id: str | None = Field(default=None, max_length=36)
    class_id: str | None = Field(default=None, max_length=36)
    student_id: str | None = Field(default=None, max_length=36)
    mode: Literal["STUDENT", "TEACHER_PREVIEW"] = "STUDENT"
    requested_by: str | None = Field(default=None, max_length=36)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=255)

    @model_validator(mode="after")
    def validate_subject(self):
        if self.mode == "STUDENT" and not self.student_id:
            raise ValueError("学生启动必须提供 student_id")
        return self


class RuntimeAction(StrictModel):
    reason: str = Field(default="用户操作", min_length=1, max_length=240)


class RuntimeExtend(StrictModel):
    minutes: int = Field(ge=5, le=120)
    reason: str = Field(min_length=1, max_length=240)


class TerminalTokenInput(StrictModel):
    idle_timeout_seconds: int = Field(default=300, ge=30, le=900)
    mode: Literal["STUDENT", "ASSIST"] = "STUDENT"


class RuntimeFacadeAction(StrictModel):
    minutes: int | None = Field(default=None, ge=1, le=240)
    reason: str | None = Field(default=None, max_length=500)
    mode: Literal["STUDENT", "ASSIST"] | None = None


class ReleaseStudentInput(StrictModel):
    student_id: str = Field(min_length=1, max_length=36)
    runtime_instance_id: str | None = Field(default=None, max_length=36)


class ReleaseContextInput(StrictModel):
    lab_release_id: str = Field(min_length=1, max_length=36)
    lab_version_id: str = Field(min_length=1, max_length=36)
    course_id: str = Field(min_length=1, max_length=36)
    class_id: str = Field(min_length=1, max_length=36)
    status: Literal["SCHEDULED", "OPEN", "CLOSED", "ARCHIVED"] = "OPEN"


class NodeRegister(StrictModel):
    node_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=96)
    agent_url: str = Field(pattern=r"^https?://", max_length=255)
    weight: int = Field(default=100, ge=1, le=1000)
    labels: dict[str, str] = Field(default_factory=dict)


class NodeSchedulePatch(StrictModel):
    scheduling_paused: bool
    weight: int | None = Field(default=None, ge=1, le=1000)


class RuntimeMaintenanceRun(StrictModel):
    node_timeout_seconds: int = Field(default=90, ge=30, le=3600)
    processing_timeout_seconds: int = Field(default=120, ge=30, le=3600)
    retry_limit: int = Field(default=20, ge=0, le=100)
    expiry_limit: int = Field(default=20, ge=0, le=100)
    max_queue_attempts: int = Field(default=5, ge=1, le=20)


class RuntimeHeartbeatResult(StrictModel):
    node_id: str
    status: Literal["READY"]
    observed_at: str
    cpu_available: float
    memory_available_mb: int
    running_groups: int
    idempotent_replay: bool


class RuntimeRequestError(StrictModel):
    code: str
    message: str


class RuntimeQueueRetryResult(StrictModel):
    runtime_request_id: str
    queue_id: str
    lab_release_id: str
    lab_version_id: str
    course_id: str | None
    class_id: str | None
    mode: str
    student_id: str | None
    status: Literal["QUEUED", "SCHEDULING", "STARTING", "RUNNING", "FAILED", "CANCELED"]
    display_status: str
    error: RuntimeRequestError | None
    runtime_group_id: str | None
    instance_ids: list[str]
    submission_status: str
    submitted_at: str | None
    started_at: str | None
    last_activity_at: str
    created_at: str
    updated_at: str
    idempotent_replay: bool


class RuntimeProcessingResult(StrictModel):
    queue_id: str
    status: str
    error_code: str | None = None


class RuntimeExpiryResult(StrictModel):
    runtime_group_id: str
    status: str
    error_code: str | None = None
    cleanup_intent: str | None = None


class RuntimeMaintenanceQueueResult(StrictModel):
    queue_id: str
    status: str
    error_code: str | None = None


class RuntimeMaintenanceResult(StrictModel):
    status: Literal["COMPLETED", "COMPLETED_WITH_ERRORS"]
    automatic: bool
    node_timeouts: list[str]
    processing_recovered: list[str]
    processing_results: list[RuntimeProcessingResult]
    expiry_results: list[RuntimeExpiryResult]
    queue_results: list[RuntimeMaintenanceQueueResult]
    completed_at: str
    idempotent_replay: bool


class ImageRegister(StrictModel):
    image_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=160)
    tag: str = Field(min_length=1, max_length=96)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    scan_status: Literal["PASSED", "FAILED", "PENDING"]
    startup_check_status: Literal["PASSED", "FAILED", "PENDING"]
    teaching_validation_status: Literal["PASSED", "FAILED", "PENDING"]
    enabled: bool = False
