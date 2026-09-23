from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeCapacityResponse(StrictModel):
    cpu_available: float
    memory_available_mb: int
    running_groups: int
    image_digests: list[str]


class RuntimeNodeResponse(StrictModel):
    node_id: str
    name: str
    status: str
    scheduling_paused: bool
    weight: int
    cpu_total: float
    memory_total_mb: int
    last_seen_at: str | None = None
    capacity: RuntimeCapacityResponse | None = None


class RuntimeNodeListResponse(StrictModel):
    items: list[RuntimeNodeResponse]
    page: int
    page_size: int
    total: int


class RuntimeImageResponse(StrictModel):
    image_id: str
    name: str
    tag: str
    digest: str
    size_bytes: int
    scan_status: str
    startup_check_status: str
    teaching_validation_status: str
    enabled: bool


class RuntimeImageListResponse(StrictModel):
    items: list[RuntimeImageResponse]
    page: int
    page_size: int
    total: int


class RuntimeQueueItemResponse(StrictModel):
    queue_id: str
    runtime_request_id: str
    status: str
    priority: int
    attempts: int
    student_id: str | None = None
    reason: str | None = None
    enqueued_at: str


class RuntimeQueueListResponse(StrictModel):
    items: list[RuntimeQueueItemResponse]
    page: int
    page_size: int
    total: int


class RuntimeInstanceSummaryResponse(StrictModel):
    runtime_instance_id: str
    student_id: str | None = None
    lab_version_id: str
    node_id: str
    node_key: str
    status: str
    started_at: str | None = None
    expires_at: str


class RuntimeInstanceListResponse(StrictModel):
    items: list[RuntimeInstanceSummaryResponse]
    page: int
    page_size: int
    total: int


class RuntimeEventResponse(StrictModel):
    event_type: str
    runtime_instance_id: str | None = None
    detail: dict[str, Any]
    occurred_at: str


class RuntimeEventListResponse(StrictModel):
    items: list[RuntimeEventResponse]
    page: int
    page_size: int
    total: int


class RuntimeOverviewResponse(StrictModel):
    nodes_ready: int
    running_instances: int
    failed_instances: int
    destroyed_instances: int
    queued_groups: int


class RuntimeRequestError(StrictModel):
    code: str
    message: str


class RuntimeRequestResponse(StrictModel):
    runtime_request_id: str
    lab_release_id: str
    lab_version_id: str
    course_id: str | None = None
    class_id: str | None = None
    mode: str
    student_id: str | None = None
    status: str
    display_status: str
    error: RuntimeRequestError | None = None
    runtime_group_id: str | None = None
    instance_ids: list[str]
    submission_status: str
    submitted_at: str | None = None
    started_at: str | None = None
    last_activity_at: str
    created_at: str
    updated_at: str


class RuntimeSchedulerResponse(StrictModel):
    score: float
    reason: str
    scheduled_at: str


class RuntimeCheckpointResultResponse(StrictModel):
    checkpoint_result_id: str
    checkpoint_id: str
    attempt: int
    status: str
    score_awarded: float
    max_score: float
    evidence: dict[str, Any]
    message: str
    judged_at: str


class RuntimeInstanceDetailResponse(StrictModel):
    runtime_instance_id: str
    runtime_group_id: str
    runtime_request_id: str
    lab_release_id: str
    lab_version_id: str
    course_id: str | None = None
    class_id: str | None = None
    student_id: str | None = None
    node_key: str
    role: str
    status: str
    display_status: str
    submission_status: str
    node_id: str
    scheduler: RuntimeSchedulerResponse
    started_at: str | None = None
    last_activity_at: str
    expires_at: str
    network_checks: dict[str, dict[str, Any]]
    current_step: int
    total_steps: int
    raw_score: float
    max_score: int
    score: float
    checkpoint_results: list[RuntimeCheckpointResultResponse]


class RuntimeLogResponse(StrictModel):
    event_type: str
    actor_user_id: str | None = None
    detail: dict[str, Any]
    occurred_at: str


class RuntimeLogListResponse(StrictModel):
    items: list[RuntimeLogResponse]
    page: int
    page_size: int
    total: int


class RuntimeArtifactResponse(StrictModel):
    artifact_id: str
    type: str
    file_id: str | None = None
    sha256: str
    size_bytes: int


class RuntimeArtifactListResponse(StrictModel):
    items: list[RuntimeArtifactResponse]
    page: int
    page_size: int
    total: int


class RuntimeTerminalTokenResponse(StrictModel):
    token: str
    expires_at: str
    runtime_instance_id: str
    websocket_path: str
    websocket_url: str
    expires_in: int
    token_transport: Literal["FIRST_FRAME"]


class RuntimeReleaseStatusCountsResponse(StrictModel):
    QUEUED: int
    SCHEDULING: int
    STARTING: int
    RUNNING: int
    FAILED: int
    CANCELED: int


class RuntimeReleaseSummaryResponse(StrictModel):
    lab_release_id: str
    lab_version_id: str
    course_id: str | None = None
    class_id: str | None = None
    release_status: str
    student_count: int
    status_counts: RuntimeReleaseStatusCountsResponse
    running_count: int
    queued_count: int
    failed_count: int
    submitted_count: int
    updated_at: str


class RuntimeReleaseStudentPendingResponse(RuntimeRequestResponse):
    """尚未生成学生工作站时的发布视图。"""

    runtime_instance_id: None = None
    current_step: int
    total_steps: int
    raw_score: float
    max_score: int


RuntimeReleaseStudentResponse = RuntimeInstanceDetailResponse | RuntimeReleaseStudentPendingResponse


class RuntimeReleaseStudentsResponse(StrictModel):
    items: list[RuntimeReleaseStudentResponse]
    page: int
    page_size: int
    total: int
    lab_release_id: str
    course_id: str | None = None
    class_id: str | None = None


class RuntimeClassStatusSummaryResponse(StrictModel):
    RUNNING: int
    QUEUED: int
    FAILED: int
    DESTROYED: int


class RuntimeClassStudentResponse(StrictModel):
    student_id: str
    runtime_request_id: str
    status: str
    updated_at: str


class RuntimeClassReadModelResponse(StrictModel):
    class_id: str
    summary: RuntimeClassStatusSummaryResponse
    students: list[RuntimeClassStudentResponse]


class RuntimeStudentReadModelResponse(StrictModel):
    student_id: str
    total_requests: int
    latest_status: str | None = None
    checkpoint_score_awarded: int
    checkpoint_score_possible: int
    updated_at: str | None = None


class RuntimeBulkActionResponse(StrictModel):
    lab_release_id: str
    action: Literal["extend-all", "remind-idle"]
    affected: int
    status: Literal["ACCEPTED"]


class RuntimeSignalActionResponse(StrictModel):
    runtime_instance_id: str
    action: Literal["remind", "unlock"]
    status: Literal["ACCEPTED"]


class RuntimeAuditLogItemResponse(StrictModel):
    event_id: str
    event_type: str
    runtime_instance_id: str | None = None
    lab_release_id: str
    course_id: str | None = None
    class_id: str | None = None
    student_id: str | None = None
    detail: dict[str, Any]
    occurred_at: str


class RuntimeAuditLogListResponse(StrictModel):
    items: list[RuntimeAuditLogItemResponse]
    page: int
    page_size: int
    total: int


class RuntimeTrafficArtifactResponse(StrictModel):
    artifact_id: str
    name: str
    runtime_instance_id: str
    lab_release_id: str
    course_id: str | None = None
    class_id: str | None = None
    student_id: str | None = None
    file_id: str
    sha256: str
    size_bytes: int
    occurred_at: str | None = None


class RuntimeTrafficArtifactListResponse(StrictModel):
    items: list[RuntimeTrafficArtifactResponse]
    page: int
    page_size: int
    total: int


class RuntimeArtifactDetailResponse(StrictModel):
    artifact_id: str
    file_id: str
    sha256: str
    size_bytes: int
    student_id: str | None = None
    lab_release_id: str
    course_id: str | None = None
    class_id: str | None = None


class RuntimeArtifactBundleResponse(StrictModel):
    download_url: str
    expires_in: int
    artifact_count: int
    status: Literal["READY"]


class RuntimeArtifactDownloadResponse(RuntimeArtifactBundleResponse):
    artifact_id: str


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


class DistributionBundleAuthorization(StrictModel):
    authorization: str = Field(min_length=40, max_length=32768)


class ArtifactBundleRequest(StrictModel):
    artifact_ids: list[str] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_artifact_ids(self):
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("日志制品不能重复")
        if any(not value or len(value) > 36 for value in self.artifact_ids):
            raise ValueError("日志制品标识无效")
        return self


class DistributionDownloadClaims(StrictModel):
    version: Literal[1]
    issuer: Literal["lab-classroom"]
    audience: Literal["lab-runtime"]
    assignment_id: str = Field(min_length=1, max_length=36)
    distribution_id: str = Field(min_length=1, max_length=36)
    distribution_type: Literal["AUDIT", "TRAFFIC"]
    student_id: str = Field(min_length=1, max_length=36)
    course_id: str = Field(min_length=1, max_length=36)
    class_id: str = Field(min_length=1, max_length=36)
    lab_release_id: str = Field(min_length=1, max_length=36)
    reference_ids: list[str] = Field(min_length=1, max_length=200)
    nonce: str = Field(min_length=16, max_length=64)
    issued_at: int = Field(ge=0)
    expires_at: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_claims(self):
        if len(self.reference_ids) != len(set(self.reference_ids)):
            raise ValueError("日志引用不能重复")
        if any(not value or len(value) > 36 for value in self.reference_ids):
            raise ValueError("日志引用标识无效")
        if self.expires_at <= self.issued_at or self.expires_at - self.issued_at > 120:
            raise ValueError("日志下载授权有效期无效")
        return self


class ArtifactStorageReference(StrictModel):
    reference_id: str = Field(min_length=1, max_length=36)
    file_id: str | None = Field(default=None, min_length=1, max_length=36)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    original_name: str = Field(min_length=1, max_length=255)


class ArtifactStorageClaims(StrictModel):
    version: Literal[1]
    issuer: Literal["lab-runtime"]
    audience: Literal["artifact-storage"]
    grant_type: Literal["DISTRIBUTION", "DIRECT"]
    assignment_id: str = Field(min_length=1, max_length=36)
    distribution_id: str | None = Field(default=None, min_length=1, max_length=36)
    distribution_type: Literal["AUDIT", "TRAFFIC"]
    subject_user_id: str = Field(min_length=1, max_length=36)
    subject_role: Literal["teacher", "student", "admin"]
    student_id: str | None = Field(default=None, min_length=1, max_length=36)
    course_id: str | None = Field(default=None, min_length=1, max_length=36)
    class_id: str | None = Field(default=None, min_length=1, max_length=36)
    lab_release_id: str | None = Field(default=None, min_length=1, max_length=36)
    references: list[ArtifactStorageReference] = Field(min_length=1, max_length=200)
    reference_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    nonce: str = Field(min_length=16, max_length=64)
    issued_at: int = Field(ge=0)
    expires_at: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_claims(self):
        reference_ids = [item.reference_id for item in self.references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("日志引用不能重复")
        if self.distribution_type == "TRAFFIC" and any(item.file_id is None for item in self.references):
            raise ValueError("流量日志必须绑定文件对象")
        if self.distribution_type == "AUDIT" and any(item.file_id is not None for item in self.references):
            raise ValueError("审计日志不能冒充文件制品")
        if self.grant_type == "DISTRIBUTION":
            if self.subject_role != "student" or not all((self.distribution_id, self.student_id, self.course_id, self.class_id, self.lab_release_id)):
                raise ValueError("日志分发能力范围不完整")
        elif self.distribution_type != "TRAFFIC":
            raise ValueError("普通制品下载仅支持文件制品")
        if self.expires_at <= self.issued_at or self.expires_at - self.issued_at > 120:
            raise ValueError("存储下载能力有效期无效")
        return self


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
