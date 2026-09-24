from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session
from app.common.errors import ApiError
from app.common.xlsx import XlsxValidationError, read_xlsx_upload

from . import models as m
from .schemas import (
    AssignmentCreate,
    AssignmentResponse,
    AssignmentSubmissionResponse,
    AttendanceCreate,
    AttendanceLinkResponse,
    AttendancePublishedResponse,
    AttendanceRecordListResponse,
    AttendanceRecordResponse,
    AttendanceSectionSummaryResponse,
    AttendanceTaskListResponse,
    AttendanceTaskResponse,
    ClassCreate,
    ClassMemberListResponse,
    ClassMemberResponse,
    CourseCatalogListResponse, CourseCreate,
    CourseLessonListResponse,
    CoursePatch,
    CourseResponse,
    CourseSummaryResponse,
    CourseListResponse,
    MemberCreate,
    MemberImportJobResponse,
    MemberLearningSummaryResponse,
    MemberRemovalResponse,
    PollAnswerIn,
    PollAnswerResponse,
    PollCreate,
    PollCreatedResponse,
    PollResponse,
    PollResultsResponse,
    QuizAttemptResponse,
    QuizCreate,
    QuizResponse,
    QuizSubmitIn,
    RosterFreezeResponse,
    StudentAssignmentListResponse,
    StudentAssignmentTaskResponse,
    StudentQuizListResponse,
    StudentQuizTaskResponse,
    StudentReadModelResponse,
    TeachingClassCreateResponse,
    TeachingClassListResponse,
    TeachingClassResponse,
    TeacherReadModelResponse,
    SubmissionIn,
)
from .service import TeachingService, entity_dict
from .xlsx import error_rows_bytes, template_bytes

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_RESPONSE = {
    200: {
        "description": "XLSX（电子表格）文件",
        "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    }
}


def service(db: Db, user: CurrentUser) -> TeachingService:
    return TeachingService(db, user)


@router.get("/course-catalogs", response_model=CourseCatalogListResponse)
def list_course_catalogs(db: Db, user: CurrentUser): return service(db, user).course_catalogs()


@router.post("/courses", status_code=201, response_model=CourseSummaryResponse)
def create_course(body: CourseCreate, db: Db, user: CurrentUser): return service(db, user).create_course(body)


@router.get("/courses", response_model=CourseListResponse)
def list_courses(db: Db, user: CurrentUser): return service(db, user).list_courses()


@router.get("/courses/{course_id}", response_model=CourseResponse)
def get_course(course_id: str, db: Db, user: CurrentUser): return service(db, user).get_course(course_id)


@router.get("/courses/{course_id}/lessons", response_model=CourseLessonListResponse)
def list_course_lessons(course_id: str, db: Db, user: CurrentUser): return service(db, user).course_lessons(course_id)


@router.patch("/courses/{course_id}", response_model=CourseResponse)
def patch_course(course_id: str, body: CoursePatch, db: Db, user: CurrentUser): return service(db, user).patch_course(course_id, body)


@router.post("/classes", status_code=201, response_model=TeachingClassCreateResponse)
def create_class(body: ClassCreate, db: Db, user: CurrentUser): return service(db, user).create_class(body)


@router.get("/classes", response_model=TeachingClassListResponse)
def list_classes(db: Db, user: CurrentUser): return service(db, user).list_classes()


@router.get("/classes/{class_id}", response_model=TeachingClassResponse)
def get_class(class_id: str, db: Db, user: CurrentUser): return service(db, user).get_class(class_id)


@router.get("/classes/{class_id}/members", response_model=ClassMemberListResponse)
def list_members(class_id: str, db: Db, user: CurrentUser, search: str = "", status: str = "ACTIVE", sort: str = "student_number", direction: str = "asc", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)): return service(db, user).members(class_id, search=search, status=status, sort=sort, direction=direction, page=page, page_size=page_size)


@router.get("/classes/{class_id}/members/import-template", response_class=StreamingResponse, responses=XLSX_RESPONSE)
def member_template(class_id: str, db: Db, user: CurrentUser):
    svc = service(db, user); svc.require("teaching.members.read"); svc.require_class(class_id)
    return StreamingResponse(BytesIO(template_bytes()), media_type=XLSX_MEDIA_TYPE, headers={"Content-Disposition": "attachment; filename=student-import-template.xlsx"})


@router.post("/classes/{class_id}/members/import", status_code=201, response_model=MemberImportJobResponse)
async def import_members(class_id: str, db: Db, user: CurrentUser, file: Annotated[UploadFile, File()], idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    try:
        content = await read_xlsx_upload(file)
    except XlsxValidationError as exc:
        raise ApiError(f"IMPORT.{exc.kind}", str(exc), 413 if exc.kind == "FILE_TOO_LARGE" else 422) from exc
    return service(db, user).import_members(class_id, content, idempotency_key or "")


@router.get("/import-jobs/{job_id}", response_model=MemberImportJobResponse)
def import_job(job_id: str, db: Db, user: CurrentUser): return service(db, user).get_import_job(job_id)


@router.get("/import-jobs/{job_id}/error-rows.xlsx", response_class=StreamingResponse, responses=XLSX_RESPONSE)
def import_errors(job_id: str, db: Db, user: CurrentUser):
    job = service(db, user).get_import_job(job_id)
    return StreamingResponse(BytesIO(error_rows_bytes(job["error_rows_json"])), media_type=XLSX_MEDIA_TYPE, headers={"Content-Disposition": "attachment; filename=student-import-errors.xlsx"})


@router.get("/classes/{class_id}/members/export.xlsx", response_class=StreamingResponse, responses=XLSX_RESPONSE)
def export_members(class_id: str, db: Db, user: CurrentUser):
    payload = service(db, user).members(class_id, page=1, page_size=10000)
    book = Workbook(); sheet = book.active; sheet.title = "班级学生"; sheet.append(["学号", "姓名", "手机号", "邮箱", "账号状态"])
    for item in payload["items"]: sheet.append([item["student_number"], item["student_name"], item["phone"], item["email"], item["status"]])
    stream = BytesIO(); book.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type=XLSX_MEDIA_TYPE, headers={"Content-Disposition": "attachment; filename=class-members.xlsx"})


@router.get("/classes/{class_id}/members/{membership_id}", response_model=ClassMemberResponse)
def member_detail(class_id: str, membership_id: str, db: Db, user: CurrentUser): return service(db, user).member_detail(class_id, membership_id)


@router.get("/classes/{class_id}/members/{membership_id}/learning-summary", response_model=MemberLearningSummaryResponse)
def member_learning_summary(class_id: str, membership_id: str, db: Db, user: CurrentUser): return service(db, user).learning_summary(class_id, membership_id)


@router.get("/classes/{class_id}/students/{student_id}/learning-summary", response_model=MemberLearningSummaryResponse)
def student_learning_summary(class_id: str, student_id: str, db: Db, user: CurrentUser): return service(db, user).learning_summary(class_id, student_id)


@router.post("/classes/{class_id}/members", status_code=201, response_model=ClassMemberResponse)
def add_member(class_id: str, body: MemberCreate, db: Db, user: CurrentUser): return service(db, user).add_member(class_id, body)


@router.post("/classes/{class_id}/roster/freeze", response_model=RosterFreezeResponse)
def freeze_roster(class_id: str, db: Db, user: CurrentUser): return service(db, user).freeze_roster(class_id)


@router.delete("/classes/{class_id}/members/{membership_id}", response_model=MemberRemovalResponse)
def remove_member(class_id: str, membership_id: str, db: Db, user: CurrentUser): return service(db, user).remove_member(class_id, membership_id)


@router.post("/attendance/tasks", status_code=201, response_model=AttendanceTaskResponse)
def create_attendance(body: AttendanceCreate, db: Db, user: CurrentUser): return service(db, user).create_attendance(body)


@router.get("/attendance/tasks", response_model=AttendanceTaskListResponse)
def list_attendance(db: Db, user: CurrentUser): return service(db, user).list_attendance()


@router.get("/attendance/tasks/{task_id}", response_model=AttendanceTaskResponse)
def get_attendance(task_id: str, db: Db, user: CurrentUser): return service(db, user).attendance(task_id)


@router.post("/attendance/tasks/{task_id}/publish", response_model=AttendancePublishedResponse)
def publish_attendance(task_id: str, db: Db, user: CurrentUser): return service(db, user).publish_attendance(task_id)


@router.post("/attendance/tasks/{task_id}/close", response_model=AttendanceTaskResponse)
def close_attendance(task_id: str, db: Db, user: CurrentUser): return service(db, user).close_attendance(task_id)


@router.get("/attendance/tasks/{task_id}/records", response_model=AttendanceRecordListResponse)
def attendance_records(task_id: str, db: Db, user: CurrentUser): return service(db, user).attendance_records(task_id)


@router.get("/attendance/section-summary", response_model=AttendanceSectionSummaryResponse)
def attendance_summary(db: Db, user: CurrentUser): return service(db, user).section_summary()


@router.get("/attendance/sign-links/{token}", response_model=AttendanceLinkResponse)
def attendance_link(token: Annotated[str, Path(min_length=20)], db: Db, user: CurrentUser): return service(db, user).attendance_link(token)


@router.post("/attendance/sign-links/{token}/sign", response_model=AttendanceRecordResponse)
def sign_attendance_by_token(token: Annotated[str, Path(min_length=20)], db: Db, user: CurrentUser): return service(db, user).sign_by_token(token)


@router.post("/attendance/{task_id}/sign", response_model=AttendanceRecordResponse)
def sign_attendance(task_id: str, token: Annotated[str, Query(min_length=20)], db: Db, user: CurrentUser): return service(db, user).sign(task_id, token)


@router.get("/attendance/{task_id}/export.xlsx", response_class=StreamingResponse, responses=XLSX_RESPONSE)
def export_attendance(task_id: str, db: Db, user: CurrentUser):
    payload = service(db, user).attendance_records(task_id)
    book = Workbook(); sheet = book.active; sheet.title = "签到结果"; sheet.append(["学生标识", "签到时间", "结果", "来源"])
    for item in payload["items"]: sheet.append([item["student_id"], item["signed_at"], item["result"], item["source"]])
    stream = BytesIO(); book.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type=XLSX_MEDIA_TYPE, headers={"Content-Disposition": "attachment; filename=attendance-records.xlsx"})


@router.post("/polls", status_code=201, response_model=PollCreatedResponse)
def create_poll(body: PollCreate, db: Db, user: CurrentUser): return service(db, user).create_poll(body)


@router.post("/polls/{poll_id}/publish", response_model=PollResponse)
def publish_poll(poll_id: str, db: Db, user: CurrentUser): return service(db, user).publish_poll(poll_id)


@router.post("/polls/{poll_id}/answers", status_code=201, response_model=PollAnswerResponse)
def answer_poll(poll_id: str, body: PollAnswerIn, db: Db, user: CurrentUser): return service(db, user).answer_poll(poll_id, body.option_id)


@router.get("/polls/{poll_id}/results", response_model=PollResultsResponse)
def poll_results(poll_id: str, db: Db, user: CurrentUser): return service(db, user).poll_results(poll_id)


@router.post("/assignments", status_code=201, response_model=AssignmentResponse)
def create_assignment(body: AssignmentCreate, db: Db, user: CurrentUser): return service(db, user).create_assignment(body)


@router.post("/assignments/{assignment_id}/publish", response_model=AssignmentResponse)
def publish_assignment(assignment_id: str, db: Db, user: CurrentUser): return service(db, user).publish_assignment(assignment_id)


@router.get("/assignments/my", response_model=StudentAssignmentListResponse)
def list_my_assignments(db: Db, user: CurrentUser): return service(db, user).student_assignments()


@router.get("/assignments/{assignment_id}/student-task", response_model=StudentAssignmentTaskResponse)
def get_my_assignment_task(assignment_id: str, db: Db, user: CurrentUser): return service(db, user).student_assignment_task(assignment_id)


@router.post("/assignments/{assignment_id}/submit", status_code=201, response_model=AssignmentSubmissionResponse)
def submit_assignment(assignment_id: str, body: SubmissionIn, db: Db, user: CurrentUser): return service(db, user).submit_assignment(assignment_id, body)


@router.post("/quizzes", status_code=201, response_model=QuizResponse)
def create_quiz(body: QuizCreate, db: Db, user: CurrentUser): return service(db, user).create_quiz(body)


@router.post("/quizzes/{quiz_id}/publish", response_model=QuizResponse)
def publish_quiz(quiz_id: str, db: Db, user: CurrentUser): return service(db, user).publish_quiz(quiz_id)


@router.get("/quizzes/my", response_model=StudentQuizListResponse)
def list_my_quizzes(db: Db, user: CurrentUser): return service(db, user).student_quizzes()


@router.get("/quizzes/{quiz_id}/student-task", response_model=StudentQuizTaskResponse)
def get_my_quiz_task(quiz_id: str, db: Db, user: CurrentUser): return service(db, user).student_quiz_task(quiz_id)


@router.post("/quizzes/{quiz_id}/attempts", status_code=201, response_model=QuizAttemptResponse)
def start_quiz(quiz_id: str, db: Db, user: CurrentUser): return service(db, user).start_quiz(quiz_id)


@router.post("/quizzes/{quiz_id}/attempts/{attempt_id}/submit", response_model=QuizAttemptResponse)
def submit_quiz(quiz_id: str, attempt_id: str, body: QuizSubmitIn, db: Db, user: CurrentUser): return service(db, user).submit_quiz(quiz_id, attempt_id, body)


@router.get("/teaching/read-model", response_model=TeacherReadModelResponse)
def teacher_read_model(db: Db, user: CurrentUser):
    svc = service(db, user); svc.require("teaching.dashboard.read")
    courses = svc.repo.list_courses(user.course_ids); classes = svc.repo.list_classes(user.class_ids); tasks = svc.repo.attendance_tasks(user.class_ids)
    return {"course_count": len(courses), "class_count": len(classes), "student_count": sum(svc.repo.members(x.class_id, limit=1)[1] for x in classes), "open_attendance_count": sum(x.status == "PUBLISHED" for x in tasks)}


@router.get("/teaching/student-read-model", response_model=StudentReadModelResponse)
def student_read_model(db: Db, user: CurrentUser):
    svc = service(db, user); svc.require("teaching.student.read"); student_id = svc.require_student()
    memberships = db.query(m.ClassMembership).filter_by(student_id=student_id, status="ACTIVE").all()
    tasks = svc.repo.attendance_tasks(frozenset(x.class_id for x in memberships))
    return {"class_count": len(memberships), "open_attendance": [{"task_id": x.task_id, "title": x.title, "expires_at": x.expires_at} for x in tasks if x.status == "PUBLISHED"]}
