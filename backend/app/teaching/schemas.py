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
    """Only lets a teacher select an already published B question.

    Version, snapshot and points are frozen from the server-side question bank
    by A.  Letting a browser provide them would make a grading proof circular.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=36)


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    due_at: datetime
    random_order: bool = False
    questions: list[QuestionRefIn] = Field(min_length=1)


class SubmissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any]


class QuizCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    time_limit_minutes: int = Field(gt=0, le=240)
    random_order: bool = False
    questions: list[QuestionRefIn] = Field(min_length=1)


class QuizSubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any]
