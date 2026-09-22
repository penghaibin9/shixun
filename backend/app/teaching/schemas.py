from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=64)
    major: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=4000)


class CoursePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    major: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["DRAFT", "ACTIVE", "ARCHIVED"] | None = None


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=64)
    course_id: str


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_number: str = Field(min_length=1, max_length=64)
    student_name: str = Field(min_length=1, max_length=80)


class AttendanceCreate(BaseModel):
    course_id: str
    class_id: str
    lesson_id: str | None = None
    task_type: Literal["CLASSROOM", "LAB", "ONLINE_ASSIGNMENT", "EXAM"]
    title: str = Field(min_length=1, max_length=160)
    starts_at: datetime
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def expires_required(cls, value: datetime) -> datetime:
        return value


class PollCreate(BaseModel):
    course_id: str
    class_id: str
    lesson_id: str | None = None
    poll_type: Literal["UNDERSTANDING", "ASSIGNMENT_COMPLETION", "TEACHING_FEEDBACK"]
    title: str = Field(min_length=1, max_length=160)
    options: list[str] = Field(min_length=2, max_length=10)


class PollAnswerIn(BaseModel):
    option_id: str


class QuestionRefIn(BaseModel):
    question_id: str
    question_version: str = Field(max_length=40)
    question_snapshot: dict[str, Any]
    max_score: int = Field(gt=0, le=1000)


class AssignmentCreate(BaseModel):
    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    due_at: datetime
    random_order: bool = False
    questions: list[QuestionRefIn] = Field(min_length=1)


class SubmissionIn(BaseModel):
    answers: dict[str, Any]
    raw_score: float = Field(ge=0)
    max_score: float = Field(gt=0)


class QuizCreate(BaseModel):
    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    time_limit_minutes: int = Field(gt=0, le=240)
    random_order: bool = False
    questions: list[QuestionRefIn] = Field(min_length=1)


class QuizSubmitIn(BaseModel):
    answers: dict[str, Any]
    raw_score: float = Field(ge=0)
    max_score: float = Field(gt=0)
