from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResourceCreate(BaseModel):
    course_id: str
    lesson_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    resource_type: str = Field(pattern="^(PPT|VIDEO|QUESTION_BANK|LAB_FILE)$")


class VersionCreate(BaseModel):
    file_id: str
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    lab_file_count: int | None = Field(default=None, ge=1)


class ResourceVideoResponse(BaseModel):
    duration_seconds: float
    width: int | None = None
    height: int | None = None
    probed_at: str


class ResourceVersionResponse(BaseModel):
    resource_version_id: str
    version_no: int
    file_id: str
    status: str
    sha256: str
    created_by: str
    created_at: str
    video: ResourceVideoResponse | None = None


class ResourceResponse(BaseModel):
    resource_id: str
    course_id: str
    lesson_id: str | None = None
    name: str
    resource_type: str
    status: str
    created_by: str
    created_at: str
    latest_version: ResourceVersionResponse | None = None


class ResourceListResponse(BaseModel):
    items: list[ResourceResponse]
    page: int
    page_size: int
    total: int


class ResourceFileResponse(BaseModel):
    file_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    sha256: str


class ResourceReadinessCounterResponse(BaseModel):
    ready: int
    required: int


class ResourceReadinessResponse(BaseModel):
    course_id: str
    theory_lessons: int
    lab_lessons: int
    ppt: ResourceReadinessCounterResponse
    theory_video: ResourceReadinessCounterResponse
    lab_file: ResourceReadinessCounterResponse
    lab_video: ResourceReadinessCounterResponse
    question_lessons: ResourceReadinessCounterResponse
    published_questions: ResourceReadinessCounterResponse
    blocking: int


class ResourceLessonResponse(BaseModel):
    course_id: str
    lesson_id: str
    lesson_kind: Literal["THEORY", "LAB"]
    chapter_no: int | None = None
    lesson_code: str
    title: str
    purpose: str | None = None
    environment: str | None = None
    principle: str | None = None
    steps_summary: str | None = None
    core_experiment: str | None = None
    linked_file_pack_id: str | None = None
    linked_video_resource_id: str | None = None
    linked_lab_definition_id: str | None = None


class ResourceLessonListResponse(BaseModel):
    items: list[ResourceLessonResponse]
    page: int
    page_size: int
    total: int


class ResourceBlueprintResponse(ResourceLessonListResponse):
    chapter_counts: dict[str, int]


class ResourceAuditCheckResponse(BaseModel):
    lesson_id: str
    lesson_code: str
    requirement: str
    passed: bool
    evidence: list[dict[str, Any]]


class ProcurementMappingResponse(BaseModel):
    requirement: str
    owner: str
    evidence: str


class ResourceAuditResponse(BaseModel):
    course_id: str
    total: int
    pass_: int = Field(alias="pass")
    warning: int
    blocking: int
    blocking_items: list[str]
    checks: list[ResourceAuditCheckResponse]
    procurement_mapping: list[ProcurementMappingResponse]
    checked_at: str

    model_config = {"populate_by_name": True}


class ResourceManifestResponse(BaseModel):
    course_id: str
    theory_lessons: int
    lab_lessons: int
    audit: ResourceAuditResponse
    status: str
    version_no: int | None = None
    generated_at: str
    content_declaration: str


class PptQualityCheckResponse(BaseModel):
    resource_version_id: str
    result: str
    knowledge_complete: bool
    layout_overflow_passed: bool
    animation_occlusion_passed: bool
    copyright_noted: bool


class PptQualityCheckInput(BaseModel):
    knowledge_complete: bool
    layout_overflow_passed: bool
    animation_occlusion_passed: bool
    copyright_noted: bool


class ReviewDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class QuestionOptionInput(BaseModel):
    key: str = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1)
    is_correct: bool = False


class QuestionCreate(BaseModel):
    course_id: str
    lesson_id: str
    question_type: str = Field(pattern="^(FILL|SINGLE|MULTIPLE|TRUE_FALSE)$")
    stem: str = Field(min_length=1)
    answer: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    options: list[QuestionOptionInput] = Field(default_factory=list)


class QuestionPatch(BaseModel):
    stem: str | None = Field(default=None, min_length=1)
    answer: list[str] | None = None
    explanation: str | None = Field(default=None, min_length=1)


class QuestionReviewDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"] = "APPROVED"
    comment: str | None = Field(default=None, max_length=1000)


class QuestionOptionResponse(BaseModel):
    key: str
    text: str
    is_correct: bool | None = None


class QuestionResponse(BaseModel):
    question_id: str
    question_type: str
    stem: str
    answer: list[str] | None = None
    status: str
    lesson_id: str
    explanation: str | None = None
    options: list[QuestionOptionResponse] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    import_job_id: str | None = None
    source_row_number: int | None = None
    submitted_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class QuestionListResponse(BaseModel):
    items: list[QuestionResponse]
    page: int
    page_size: int
    total: int


class QuestionStatusResponse(BaseModel):
    question_id: str
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class QuestionImportErrorResponse(BaseModel):
    row_number: int | None = None
    field: str
    code: str
    message: str


class QuestionImportRowResponse(BaseModel):
    row_number: int
    status: str
    question_id: str | None = None
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class QuestionImportJobResponse(BaseModel):
    import_job_id: str
    job_id: str
    course_id: str
    status: str
    total_rows: int
    total_count: int
    success_count: int
    imported_count: int
    failure_count: int
    error_count: int
    review_queue_count: int
    original_filename: str
    request_sha256: str
    created_by: str
    created_at: datetime
    completed_at: datetime | None = None
    rows: list[QuestionImportRowResponse]
    error_rows: list[QuestionImportErrorResponse]


class QuestionReviewQueueItem(QuestionResponse):
    course_id: str
    lesson_code: str
    lesson_title: str
    can_review: bool


class QuestionReviewQueueResponse(BaseModel):
    items: list[QuestionReviewQueueItem]
    page: int
    page_size: int
    total: int


class QuestionCoverageItem(BaseModel):
    lesson_id: str
    lesson_code: str
    types: list[str]
    question_count: int
    passed: bool


class QuestionCoverageResponse(BaseModel):
    items: list[QuestionCoverageItem]
    total: int
    passed: int


class AuditRequest(BaseModel):
    course_id: str


class FreezeRequest(BaseModel):
    course_id: str
