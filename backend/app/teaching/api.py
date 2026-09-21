from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session

from . import models as m
from .schemas import AssignmentCreate, AttendanceCreate, ClassCreate, CourseCreate, CoursePatch, MemberCreate, PollAnswerIn, PollCreate, QuizCreate, QuizSubmitIn, SubmissionIn
from .service import TeachingService, entity_dict
from .xlsx import error_rows_bytes, template_bytes

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]


def service(db: Db, user: CurrentUser) -> TeachingService:
    return TeachingService(db, user)


@router.post("/courses", status_code=201)
def create_course(body: CourseCreate, db: Db, user: CurrentUser): return service(db, user).create_course(body)


@router.get("/courses")
def list_courses(db: Db, user: CurrentUser): return service(db, user).list_courses()


@router.get("/courses/{course_id}")
def get_course(course_id: str, db: Db, user: CurrentUser): return service(db, user).get_course(course_id)


@router.patch("/courses/{course_id}")
def patch_course(course_id: str, body: CoursePatch, db: Db, user: CurrentUser): return service(db, user).patch_course(course_id, body)


@router.post("/classes", status_code=201)
def create_class(body: ClassCreate, db: Db, user: CurrentUser): return service(db, user).create_class(body)


@router.get("/classes")
def list_classes(db: Db, user: CurrentUser): return service(db, user).list_classes()


@router.get("/classes/{class_id}")
def get_class(class_id: str, db: Db, user: CurrentUser): return service(db, user).get_class(class_id)


@router.get("/classes/{class_id}/members")
def list_members(class_id: str, db: Db, user: CurrentUser, search: str = "", status: str = "ACTIVE", sort: str = "student_number", direction: str = "asc", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)): return service(db, user).members(class_id, search=search, status=status, sort=sort, direction=direction, page=page, page_size=page_size)


@router.get("/classes/{class_id}/members/import-template")
def member_template(class_id: str, db: Db, user: CurrentUser):
    svc = service(db, user); svc.require("teaching.members.read"); svc.require_class(class_id)
    return StreamingResponse(BytesIO(template_bytes()), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=student-import-template.xlsx"})


@router.post("/classes/{class_id}/members/import", status_code=201)
async def import_members(class_id: str, db: Db, user: CurrentUser, file: Annotated[UploadFile, File()], idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    return service(db, user).import_members(class_id, await file.read(), idempotency_key or "")


@router.get("/import-jobs/{job_id}")
def import_job(job_id: str, db: Db, user: CurrentUser): return service(db, user).get_import_job(job_id)


@router.get("/import-jobs/{job_id}/error-rows.xlsx")
def import_errors(job_id: str, db: Db, user: CurrentUser):
    job = service(db, user).get_import_job(job_id)
    return StreamingResponse(BytesIO(error_rows_bytes(job["error_rows_json"])), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=student-import-errors.xlsx"})


@router.get("/classes/{class_id}/members/export.xlsx")
def export_members(class_id: str, db: Db, user: CurrentUser):
    payload = service(db, user).members(class_id, page=1, page_size=10000)
    book = Workbook(); sheet = book.active; sheet.title = "班级学生"; sheet.append(["学号", "姓名", "手机号", "邮箱", "账号状态"])
    for item in payload["items"]: sheet.append([item["student_number"], item["student_name"], item["phone"], item["email"], item["status"]])
    stream = BytesIO(); book.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=class-members.xlsx"})


@router.get("/classes/{class_id}/members/{membership_id}")
def member_detail(class_id: str, membership_id: str, db: Db, user: CurrentUser): return service(db, user).member_detail(class_id, membership_id)


@router.get("/classes/{class_id}/members/{membership_id}/learning-summary")
def member_learning_summary(class_id: str, membership_id: str, db: Db, user: CurrentUser): return service(db, user).learning_summary(class_id, membership_id)


@router.get("/classes/{class_id}/students/{student_id}/learning-summary")
def student_learning_summary(class_id: str, student_id: str, db: Db, user: CurrentUser): return service(db, user).learning_summary(class_id, student_id)


@router.post("/classes/{class_id}/members", status_code=201)
def add_member(class_id: str, body: MemberCreate, db: Db, user: CurrentUser): return service(db, user).add_member(class_id, body)


@router.delete("/classes/{class_id}/members/{membership_id}")
def remove_member(class_id: str, membership_id: str, db: Db, user: CurrentUser): return service(db, user).remove_member(class_id, membership_id)


@router.post("/attendance/tasks", status_code=201)
def create_attendance(body: AttendanceCreate, db: Db, user: CurrentUser): return service(db, user).create_attendance(body)


@router.get("/attendance/tasks")
def list_attendance(db: Db, user: CurrentUser): return service(db, user).list_attendance()


@router.get("/attendance/tasks/{task_id}")
def get_attendance(task_id: str, db: Db, user: CurrentUser): return service(db, user).attendance(task_id)


@router.post("/attendance/tasks/{task_id}/publish")
def publish_attendance(task_id: str, db: Db, user: CurrentUser): return service(db, user).publish_attendance(task_id)


@router.post("/attendance/tasks/{task_id}/close")
def close_attendance(task_id: str, db: Db, user: CurrentUser): return service(db, user).close_attendance(task_id)


@router.get("/attendance/tasks/{task_id}/records")
def attendance_records(task_id: str, db: Db, user: CurrentUser): return service(db, user).attendance_records(task_id)


@router.get("/attendance/section-summary")
def attendance_summary(db: Db, user: CurrentUser): return service(db, user).section_summary()


@router.post("/attendance/{task_id}/sign")
def sign_attendance(task_id: str, token: Annotated[str, Query(min_length=20)], db: Db, user: CurrentUser): return service(db, user).sign(task_id, token)


@router.get("/attendance/{task_id}/export.xlsx")
def export_attendance(task_id: str, db: Db, user: CurrentUser):
    payload = service(db, user).attendance_records(task_id)
    book = Workbook(); sheet = book.active; sheet.title = "签到结果"; sheet.append(["学生标识", "签到时间", "结果", "来源"])
    for item in payload["items"]: sheet.append([item["student_id"], item["signed_at"], item["result"], item["source"]])
    stream = BytesIO(); book.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=attendance-records.xlsx"})


@router.post("/polls", status_code=201)
def create_poll(body: PollCreate, db: Db, user: CurrentUser): return service(db, user).create_poll(body)


@router.post("/polls/{poll_id}/publish")
def publish_poll(poll_id: str, db: Db, user: CurrentUser): return service(db, user).publish_poll(poll_id)


@router.post("/polls/{poll_id}/answers", status_code=201)
def answer_poll(poll_id: str, body: PollAnswerIn, db: Db, user: CurrentUser): return service(db, user).answer_poll(poll_id, body.option_id)


@router.get("/polls/{poll_id}/results")
def poll_results(poll_id: str, db: Db, user: CurrentUser): return service(db, user).poll_results(poll_id)


@router.post("/assignments", status_code=201)
def create_assignment(body: AssignmentCreate, db: Db, user: CurrentUser): return service(db, user).create_assignment(body)


@router.post("/assignments/{assignment_id}/publish")
def publish_assignment(assignment_id: str, db: Db, user: CurrentUser): return service(db, user).publish_assignment(assignment_id)


@router.post("/assignments/{assignment_id}/submit", status_code=201)
def submit_assignment(assignment_id: str, body: SubmissionIn, db: Db, user: CurrentUser): return service(db, user).submit_assignment(assignment_id, body)


@router.post("/quizzes", status_code=201)
def create_quiz(body: QuizCreate, db: Db, user: CurrentUser): return service(db, user).create_quiz(body)


@router.post("/quizzes/{quiz_id}/publish")
def publish_quiz(quiz_id: str, db: Db, user: CurrentUser): return service(db, user).publish_quiz(quiz_id)


@router.post("/quizzes/{quiz_id}/attempts", status_code=201)
def start_quiz(quiz_id: str, db: Db, user: CurrentUser): return service(db, user).start_quiz(quiz_id)


@router.post("/quizzes/{quiz_id}/attempts/{attempt_id}/submit")
def submit_quiz(quiz_id: str, attempt_id: str, body: QuizSubmitIn, db: Db, user: CurrentUser): return service(db, user).submit_quiz(quiz_id, attempt_id, body)


@router.get("/teaching/read-model")
def teacher_read_model(db: Db, user: CurrentUser):
    svc = service(db, user); svc.require("teaching.dashboard.read")
    courses = svc.repo.list_courses(user.course_ids); classes = svc.repo.list_classes(user.class_ids); tasks = svc.repo.attendance_tasks(user.class_ids)
    return {"course_count": len(courses), "class_count": len(classes), "student_count": sum(svc.repo.members(x.class_id, limit=1)[1] for x in classes), "open_attendance_count": sum(x.status == "PUBLISHED" for x in tasks)}


@router.get("/teaching/student-read-model")
def student_read_model(db: Db, user: CurrentUser):
    svc = service(db, user); svc.require("teaching.student.read"); student_id = svc.require_student()
    memberships = db.query(m.ClassMembership).filter_by(student_id=student_id).all()
    tasks = svc.repo.attendance_tasks(frozenset(x.class_id for x in memberships))
    return {"class_count": len(memberships), "open_attendance": [{"task_id": x.task_id, "title": x.title, "expires_at": x.expires_at} for x in tasks if x.status == "PUBLISHED"]}
