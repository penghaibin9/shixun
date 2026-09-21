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
