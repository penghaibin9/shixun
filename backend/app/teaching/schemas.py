from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


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


class StudentTaskOptionResponse(BaseModel):
    """One browser-renderable option from an immutable question reference."""

    key: str
    text: str


class StudentTaskQuestionResponse(BaseModel):
    """A student-safe projection of A's immutable question reference.

    The full frozen snapshot contains the answer key and proof-only evidence.
    It is intentionally never returned to the browser: the browser receives
    only what it needs to render an answer form and must submit answers keyed
    by ``question_ref_id``.
    """

    question_ref_id: str
    question_id: str
    question_type: str
    stem: str
    options: list[StudentTaskOptionResponse] = Field(default_factory=list)


class StudentAssignmentListItemResponse(BaseModel):
    assignment_id: str
    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str
    due_at: datetime
    status: str
    submission_status: str | None = None


class StudentAssignmentListResponse(BaseModel):
    items: list[StudentAssignmentListItemResponse]


class StudentAssignmentTaskResponse(StudentAssignmentListItemResponse):
    questions: list[StudentTaskQuestionResponse]


class StudentQuizListItemResponse(BaseModel):
    quiz_id: str
    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str
    time_limit_minutes: int
    status: str
    attempt_status: str | None = None


class StudentQuizListResponse(BaseModel):
    items: list[StudentQuizListItemResponse]


class StudentQuizTaskResponse(StudentQuizListItemResponse):
    questions: list[StudentTaskQuestionResponse]


# The models below describe browser-visible projections returned by the
# teaching service.  They deliberately do not use the SQLAlchemy entities as
# response models: a few entity fields (for example an attendance token hash)
# are persistence details and must not become part of the public contract.


class CourseResponse(BaseModel):
    course_id: str
    name: str
    term: str
    owner_teacher_id: str
    major: str | None = None
    description: str | None = None
    status: str
    created_at: datetime


class CourseSummaryResponse(CourseResponse):
    theory_lesson_count: int
    lab_lesson_count: int


class CourseListResponse(BaseModel):
    items: list[CourseSummaryResponse]
    page: int
    page_size: int
    total: int


class CourseLessonResponse(BaseModel):
    lesson_id: str
    course_id: str
    chapter_id: str
    lesson_code: str
    title: str
    sequence: int
    lesson_type: str
    chapter_title: str
    chapter_sequence: int


class CourseLessonListResponse(BaseModel):
    items: list[CourseLessonResponse]
    total: int
    theory_count: int
    lab_count: int


class TeachingClassResponse(BaseModel):
    class_id: str
    name: str
    term: str
    owner_teacher_id: str
    created_at: datetime
    roster_frozen_at: datetime | None = None
    roster_frozen_by: str | None = None
    roster_snapshot_hash: str | None = None


class TeachingClassCreateResponse(TeachingClassResponse):
    course_id: str


class TeachingClassListResponse(BaseModel):
    items: list[TeachingClassResponse]
    page: int
    page_size: int
    total: int


class ClassMemberResponse(BaseModel):
    class_membership_id: str
    class_id: str
    student_id: str
    student_number: str
    student_name: str
    phone: str | None = None
    email: str | None = None
    status: str
    joined_at: datetime


class ClassMemberListResponse(BaseModel):
    items: list[ClassMemberResponse]
    page: int
    page_size: int
    total: int


class MemberImportErrorRowResponse(BaseModel):
    """One recoverable spreadsheet row error returned to the teacher."""

    row_number: int | None = None
    student_number: str = ""
    student_name: str = ""
    class_name: str = ""
    phone: str = ""
    email: str = ""
    reason: str = ""


class MemberImportJobResponse(BaseModel):
    job_id: str
    class_id: str
    idempotency_key: str
    request_sha256: str | None = None
    status: str
    success_count: int
    failure_count: int
    duplicate_count: int
    error_rows_json: list[MemberImportErrorRowResponse] = Field(default_factory=list)
    created_by: str
    created_at: datetime


class MemberRemovalResponse(BaseModel):
    class_membership_id: str
    status: str


class RosterFreezeResponse(BaseModel):
    class_id: str
    course_id: str
    status: str
    member_count: int
    snapshot_hash: str | None = None
    frozen_at: datetime | None = None
    frozen_by: str | None = None


class LearningAttendanceSummaryResponse(BaseModel):
    signed: int
    total: int


class PendingAggregationResponse(BaseModel):
    status: str
    label: str


class MemberLearningSummaryResponse(BaseModel):
    student_id: str
    attendance: LearningAttendanceSummaryResponse
    assignment_submitted: int
    quiz_completed: int
    experiment: PendingAggregationResponse
    grade: PendingAggregationResponse
    risk: PendingAggregationResponse


class AttendanceTaskResponse(BaseModel):
    task_id: str
    course_id: str
    class_id: str
    lesson_id: str | None = None
    task_type: str
    title: str
    starts_at: datetime
    expires_at: datetime
    status: str
    created_by: str


class AttendancePublishedResponse(AttendanceTaskResponse):
    sign_token: str
    sign_url: str


class AttendanceTaskListResponse(BaseModel):
    items: list[AttendanceTaskResponse]
    page: int
    page_size: int
    total: int


class AttendanceRecordResponse(BaseModel):
    record_id: str
    task_id: str
    student_id: str
    signed_at: datetime
    result: str
    source: str


class AttendanceRecordListResponse(BaseModel):
    items: list[AttendanceRecordResponse]
    page: int
    page_size: int
    total: int


class AttendanceLinkResponse(BaseModel):
    task_id: str
    title: str
    task_type: str
    starts_at: datetime
    expires_at: datetime
    status: str


class AttendanceSectionSummaryItemResponse(BaseModel):
    task_id: str
    lesson: str | None = None
    task_type: str
    expected: int
    present: int
    late: int
    absent: int
    status: str


class AttendanceSectionSummaryResponse(BaseModel):
    items: list[AttendanceSectionSummaryItemResponse]
    page: int
    page_size: int
    total: int


class PollOptionResponse(BaseModel):
    option_id: str
    poll_id: str
    label: str
    sequence: int


class PollResponse(BaseModel):
    poll_id: str
    course_id: str
    class_id: str
    lesson_id: str | None = None
    poll_type: str
    title: str
    status: str
    created_by: str


class PollCreatedResponse(PollResponse):
    options: list[PollOptionResponse]


class PollAnswerResponse(BaseModel):
    answer_id: str
    poll_id: str
    option_id: str
    student_id: str
    answered_at: datetime


class PollResultItemResponse(BaseModel):
    option_id: str
    label: str
    count: int


class PollResultsResponse(BaseModel):
    poll_type: str
    items: list[PollResultItemResponse]


class AssignmentResponse(BaseModel):
    assignment_id: str
    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str
    due_at: datetime
    random_order: bool
    status: str
    created_by: str


class AssignmentSubmissionResponse(BaseModel):
    submission_id: str
    assignment_id: str
    student_id: str
    answers_json: dict[str, JsonValue]
    raw_score: float
    max_score: float
    status: str
    submitted_at: datetime


class QuizResponse(BaseModel):
    quiz_id: str
    course_id: str
    class_id: str
    lesson_id: str | None = None
    title: str
    time_limit_minutes: int
    random_order: bool
    status: str
    created_by: str


class QuizAttemptResponse(BaseModel):
    attempt_id: str
    quiz_id: str
    student_id: str
    status: str
    started_at: datetime
    submitted_at: datetime | None = None
    raw_score: float | None = None
    max_score: float | None = None


class TeacherReadModelResponse(BaseModel):
    course_count: int
    class_count: int
    student_count: int
    open_attendance_count: int


class StudentOpenAttendanceResponse(BaseModel):
    task_id: str
    title: str
    expires_at: datetime


class StudentReadModelResponse(BaseModel):
    class_count: int
    open_attendance: list[StudentOpenAttendanceResponse]
