from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, JsonValue


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


# 下面的读取模型是 F 线对前端和跨线消费者公开的稳定 JSON 形状。它们刻意不
# 使用 ``dict`` / ``Any`` 作为整个响应，避免路由在未声明的情况下泄漏新的事实字段。
class ReadResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GradingPolicyItemResponse(ReadResponseModel):
    component: str
    weight_percent: float


class GradingPolicyResponse(ReadResponseModel):
    course_id: str
    status: str
    version_no: int | None
    items: list[GradingPolicyItemResponse]
    effective_at: datetime | None = None


class EventConsumptionResponse(ReadResponseModel):
    status: str
    event_id: str | None = None
    grade_event_id: str | None = None
    source_proof_event_id: str | None = None
    score_event_id: str | None = None


class GradebookScoreResponse(ReadResponseModel):
    student_id: str
    total_score: float
    completeness: str


class GradebookStateResponse(ReadResponseModel):
    gradebook_id: str
    course_id: str
    class_id: str
    policy_version: int
    status: str
    calculated_at: datetime
    posted_at: datetime | None


class GradebookResponse(ReadResponseModel):
    course_id: str
    status: str
    items: list[GradebookScoreResponse]
    class_id: str | None = None
    gradebook_id: str | None = None
    policy_version: int | None = None
    calculated_at: datetime | None = None
    posted_at: datetime | None = None
    reason: str | None = None


class GradeEventSourceResponse(ReadResponseModel):
    grade_event_id: str
    source_type: str
    source_id: str
    lab_release_id: str | None = None
    lesson_id: str | None = None
    raw_score: float
    max_score: float
    normalized_score: float
    source_verification_status: str
    source_proof_issuer: str | None = None
    source_proof_digest: str | None = None
    occurred_at: datetime
    event_id: str


class GradebookTraceComponentResponse(ReadResponseModel):
    component: str
    score: float
    weight_percent: float | None
    weighted_score: float
    sources: list[GradeEventSourceResponse]


class GradebookTraceResponse(ReadResponseModel):
    status: str
    student_id: str
    total_score: float | None = None
    policy_version: int | None = None
    source_snapshot_event_ids: list[str] | None = None
    components: list[GradebookTraceComponentResponse] | None = None
    sources: list[GradeEventSourceResponse] | None = None


class AnalyticsRankingResponse(ReadResponseModel):
    student_id: str
    total_score: float | None = None
    completeness: str | None = None
    score: float | None = None


class AnalyticsOverviewResponse(ReadResponseModel):
    status: str
    course_id: str | None = None
    reason: str | None = None
    student_count: int | None = None
    avg_assignment: float | None = None
    avg_quiz: float | None = None
    attendance_rate: float | None = None
    course_average: float | None = None
    ranking: list[AnalyticsRankingResponse] | None = None
    student_rank: int | None = None
    source_event_ids: list[str] | None = None


class AnalyticsSectionDistributionResponse(ReadResponseModel):
    range_0_59: int = Field(alias="0-59")
    range_60_69: int = Field(alias="60-69")
    range_70_79: int = Field(alias="70-79")
    range_80_89: int = Field(alias="80-89")
    range_90_100: int = Field(alias="90-100")


class AnalyticsSectionResponse(ReadResponseModel):
    status: str
    course_id: str | None = None
    lesson_id: str | None = None
    average: float | None = None
    distribution: AnalyticsSectionDistributionResponse | None = None
    ranking: list[AnalyticsRankingResponse] | None = None


class AnalyticsStudentLabResponse(ReadResponseModel):
    student_id: str
    sum_lab_score: float
    submitted_count: int
    unsubmitted_count: int


class AnalyticsStudentLabListResponse(ReadResponseModel):
    status: str
    items: list[AnalyticsStudentLabResponse]


class AnalyticsLabResponse(ReadResponseModel):
    lab_release_id: str
    max_score: float
    submitted_students: int
    unsubmitted_students: int
    avg_score: float


class AnalyticsLabListResponse(ReadResponseModel):
    status: str
    items: list[AnalyticsLabResponse]


class StudentRiskResponse(ReadResponseModel):
    student_id: str
    risk_type: str
    evidence: dict[str, JsonValue]
    status: str


class StudentRiskListResponse(ReadResponseModel):
    status: str
    items: list[StudentRiskResponse]


class LearningSummaryResponse(ReadResponseModel):
    course_id: str
    class_id: str
    student_id: str | None
    status: str
    grade: GradebookResponse
    risk: StudentRiskListResponse
    analytics: AnalyticsOverviewResponse
    missing_upstream: list[str]


class GradebookIncompleteStudentResponse(ReadResponseModel):
    student_id: str
    missing_components: list[str]


class GradebookIntegrityResponse(ReadResponseModel):
    student_count: int
    enabled_components: list[str]
    incomplete_students: list[GradebookIncompleteStudentResponse]
    source_snapshot_present: bool
    source_event_ids: list[str]
    unapplied_source_event_ids: list[str]
    missing_source_event_ids: list[str]


class RosterSnapshotResponse(ReadResponseModel):
    source_event_id: str
    aggregate_id: str
    occurred_at: datetime
    course_id: str
    class_id: str
    member_count: int
    snapshot_hash: str
    frozen_at: datetime


class ArchiveResourceManifestResponse(ReadResponseModel):
    source_event_id: str
    aggregate_id: str
    occurred_at: datetime
    course_id: str
    manifest_id: str
    version_no: int


class ArchivePrecheckResponse(ReadResponseModel):
    status: str
    checks: dict[str, bool]
    blocking: int
    blocking_items: list[str]
    roster_snapshot: RosterSnapshotResponse | None
    resource_manifest: ArchiveResourceManifestResponse | None
    gradebook_integrity: GradebookIntegrityResponse


class ArchiveArtifactResponse(ReadResponseModel):
    type: str
    file_id: str | None = None
    evidence_ref: str
    sha256: str | None = None
    size_bytes: int | None = None


class ArchiveManifestPayloadResponse(ReadResponseModel):
    course_id: str
    class_id: str
    gradebook_id: str
    policy_version: int
    roster_snapshot: RosterSnapshotResponse
    resource_manifest: ArchiveResourceManifestResponse
    source_event_ids: list[str]
    artifacts: list[ArchiveArtifactResponse]
    archived_at: datetime


class ArchiveResponse(ReadResponseModel):
    status: str
    precheck: ArchivePrecheckResponse | None = None
    manifest: ArchiveManifestPayloadResponse | None = None


class ArchiveManifestReadResponse(ReadResponseModel):
    status: str | None = None
    course_id: str | None = None
    class_id: str | None = None
    gradebook_id: str | None = None
    policy_version: int | None = None
    roster_snapshot: RosterSnapshotResponse | None = None
    resource_manifest: ArchiveResourceManifestResponse | None = None
    source_event_ids: list[str] | None = None
    artifacts: list[ArchiveArtifactResponse] | None = None
    archived_at: datetime | None = None


class AuditEventResponse(ReadResponseModel):
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


class AuditEventListResponse(ReadResponseModel):
    items: list[AuditEventResponse]
    page: int
    page_size: int
    total: int


class AuditIngestResponse(ReadResponseModel):
    status: str
    audit_event_id: str
