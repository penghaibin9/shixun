from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.common.errors import ApiError
from app.database import get_session

from .catalog import COURSE_ID
from .question_xlsx import MAX_XLSX_UPLOAD_BYTES
from .schemas import (
    AuditRequest,
    FreezeRequest,
    PptQualityCheckInput,
    QuestionCoverageResponse,
    QuestionCreate,
    QuestionImportJobResponse,
    QuestionListResponse,
    QuestionPatch,
    QuestionResponse,
    QuestionReviewDecision,
    QuestionReviewQueueResponse,
    QuestionStatusResponse,
    ResourceCreate,
    ReviewDecision,
    VersionCreate,
)
from .service import ResourceService

router = APIRouter(prefix="/api/v1", tags=["课程资源"])
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_RESPONSE = {
    200: {
        "description": "XLSX（电子表格）文件",
        "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    }
}


def service(session: Session, user) -> ResourceService:
    return ResourceService(session, user)


async def read_question_upload(file: UploadFile) -> bytes:
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MAX_XLSX_UPLOAD_BYTES:
            raise ApiError("QUESTION_IMPORT.FILE_TOO_LARGE", "题库导入文件不能超过 10 MB", 413)
    return bytes(content)


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
    result["chapter_counts"] = {
        str(chapter): sum(item["chapter_no"] == chapter for item in result["items"])
        for chapter in sorted({item["chapter_no"] for item in result["items"] if item["chapter_no"] is not None})
    }
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


@router.get("/questions", response_model=QuestionListResponse, response_model_exclude_none=True)
def list_questions(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).list_questions(course_id)


@router.post("/questions", status_code=201, response_model=QuestionResponse)
def create_question(data: QuestionCreate, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).create_question(data)


@router.get("/questions/import-template.xlsx", response_class=StreamingResponse, responses=XLSX_RESPONSE)
def question_import_template(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    content = service(session, user).question_template(course_id)
    return StreamingResponse(
        BytesIO(content),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=question-import-template.xlsx"},
    )


@router.post("/questions/import", status_code=201, response_model=QuestionImportJobResponse)
async def import_questions(
    user: CurrentUser,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    course_id: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    content = await read_question_upload(file)
    return service(session, user).import_questions(course_id, content, file.filename or "questions.xlsx", idempotency_key)


@router.get("/questions/import-jobs/{job_id}", response_model=QuestionImportJobResponse)
def get_question_import_job(job_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).get_question_import_job(job_id)


@router.get("/questions/import-jobs/{job_id}/error-rows.xlsx", response_class=StreamingResponse, responses=XLSX_RESPONSE)
def question_import_error_rows(job_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    content = service(session, user).question_import_errors_xlsx(job_id)
    return StreamingResponse(
        BytesIO(content),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename=question-import-errors-{job_id}.xlsx"},
    )


@router.get("/questions/review-queue", response_model=QuestionReviewQueueResponse)
def question_review_queue(
    user: CurrentUser,
    session: Session = Depends(get_session),
    course_id: str = COURSE_ID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    return service(session, user).review_queue(course_id, page, page_size)


@router.get("/questions/coverage", response_model=QuestionCoverageResponse)
def question_coverage(user: CurrentUser, session: Session = Depends(get_session), course_id: str = COURSE_ID):
    return service(session, user).coverage(course_id)


@router.patch("/questions/{question_id}", response_model=QuestionStatusResponse)
def patch_question(question_id: str, data: QuestionPatch, user: CurrentUser, session: Session = Depends(get_session)):
    return service(session, user).patch_question(question_id, data)


@router.post("/questions/{question_id}/review", response_model=QuestionStatusResponse)
def review_question(question_id: str, user: CurrentUser, data: QuestionReviewDecision | None = None, session: Session = Depends(get_session)):
    return service(session, user).review_question(question_id, data)
