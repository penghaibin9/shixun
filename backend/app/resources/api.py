from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session

from .catalog import COURSE_ID
from .models import Question, QuestionBank, QuestionExplanation, QuestionLessonMap
from .schemas import AuditRequest, FreezeRequest, PptQualityCheckInput, QuestionCreate, QuestionPatch, ResourceCreate, ReviewDecision, VersionCreate
from .service import ResourceService

router = APIRouter(prefix="/api/v1", tags=["课程资源"])


def service(session: Session, user) -> ResourceService:
    return ResourceService(session, user)


@router.get("/resources")
def list_resources(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID, status: str | None = None, name: str | None = None, resource_type: str | None = None):
    return service(session, user).list_resources(course_id, status, name, resource_type)


@router.post("/resources", status_code=201)
def create_resource(data: ResourceCreate, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).create_resource(data)


@router.post("/resources/files", status_code=201)
async def upload_resource_file(user: CurrentUser, course_id: str = Form(...), file: UploadFile = File(...), session: Session = Depends(get_session)):
    return await service(session, user).upload_file(course_id, file)


@router.get("/resources/readiness")
def resource_readiness(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).readiness(course_id)


@router.get("/resources/theory-lessons")
def theory_lessons(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).lessons(course_id, "THEORY")


@router.get("/resources/lab-lessons")
def lab_lessons(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).lessons(course_id, "LAB")


@router.get("/resources/course-blueprint/{course_id}")
def blueprint(course_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    result = service(session, user).lessons(course_id)
    result["chapter_counts"] = {"1": 5, "2": 3, "3": 6, "4": 7, "5": 7, "6": 5, "7": 4}
    return result


@router.post("/resources/audit/run")
def run_audit(data: AuditRequest, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).audit(data.course_id)


@router.get("/resources/audit/latest")
def latest_audit(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).latest_audit(course_id)


@router.post("/resources/delivery/freeze")
def freeze(data: FreezeRequest, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).freeze(data.course_id)


@router.get("/resources/delivery/manifest.json")
def manifest_json(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).manifest(course_id)


@router.get("/resources/delivery/manifest.xlsx")
def manifest_xlsx(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    content = service(session, user).manifest_xlsx(course_id)
    return StreamingResponse(BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=course-resource-manifest.xlsx"})


@router.get("/resources/{resource_id}")
def get_resource(resource_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).get_resource(resource_id)


@router.get("/resources/{resource_id}/download")
def download_resource(resource_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    path, name, mime_type = service(session, user).download(resource_id)
    return FileResponse(path, filename=name, media_type=mime_type)


@router.post("/resources/{resource_id}/versions", status_code=201)
def create_version(resource_id: str, data: VersionCreate, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).create_version(resource_id, data)


@router.post("/resources/{resource_id}/versions/{version_id}/quality-check")
def ppt_quality_check(resource_id: str, version_id: str, data: PptQualityCheckInput, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).check_ppt_quality(resource_id, version_id, data)


@router.post("/resources/{resource_id}/submit-review")
def submit_review(resource_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).transition(resource_id, "submit-review")


@router.post("/resources/{resource_id}/approve")
def approve(resource_id: str, data: ReviewDecision, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).transition(resource_id, "approve", data.comment)


@router.post("/resources/{resource_id}/reject")
def reject(resource_id: str, data: ReviewDecision, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).transition(resource_id, "reject", data.comment)


@router.post("/resources/{resource_id}/publish")
def publish(resource_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).transition(resource_id, "publish")


@router.get("/questions")
def list_questions(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    svc = service(session, user); svc._course(course_id)
    rows = session.execute(select(Question, QuestionLessonMap.lesson_id, QuestionExplanation.explanation).join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id).join(QuestionLessonMap, QuestionLessonMap.question_id == Question.question_id).join(QuestionExplanation, QuestionExplanation.question_id == Question.question_id).where(QuestionBank.course_id == course_id)).all()
    items = [svc.question_dict(q, lesson_id, explanation) for q, lesson_id, explanation in rows if user.role != "student" or q.status == "PUBLISHED"]
    if user.role == "student":
        for item in items:
            item.pop("answer", None)
            item.pop("explanation", None)
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/questions", status_code=201)
def create_question(data: QuestionCreate, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).create_question(data)


@router.patch("/questions/{question_id}")
def patch_question(question_id: str, data: QuestionPatch, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).patch_question(question_id, data)


@router.post("/questions/{question_id}/review")
def review_question(question_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).review_question(question_id)


@router.get("/questions/coverage")
def question_coverage(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).coverage(course_id)
