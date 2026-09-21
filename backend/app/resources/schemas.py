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


class QuestionCreate(BaseModel):
    course_id: str
    lesson_id: str
    question_type: str = Field(pattern="^(FILL|SINGLE|MULTIPLE|TRUE_FALSE)$")
    stem: str = Field(min_length=1)
    answer: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    options: list[dict] = Field(default_factory=list)


class QuestionPatch(BaseModel):
    stem: str | None = Field(default=None, min_length=1)
    answer: list[str] | None = None
    explanation: str | None = Field(default=None, min_length=1)


class AuditRequest(BaseModel):
    course_id: str


class FreezeRequest(BaseModel):
    course_id: str
