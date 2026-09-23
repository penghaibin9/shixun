from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session
from .schemas import (
    AnalyticsLabListResponse,
    AnalyticsOverviewResponse,
    AnalyticsSectionResponse,
    AnalyticsStudentLabListResponse,
    ArchiveInput,
    ArchiveManifestPayloadResponse,
    ArchiveManifestReadResponse,
    ArchivePrecheckResponse,
    ArchiveResponse,
    AuditEventListResponse,
    AuditIngest,
    AuditIngestResponse,
    EventConsumptionResponse,
    EventEnvelope,
    GradebookResponse,
    GradebookStateResponse,
    GradebookTraceResponse,
    GradingPolicyResponse,
    LearningSummaryResponse,
    PolicyInput,
    RecalculateInput,
    StudentRiskListResponse,
)
from .service import GradingService

router = APIRouter(prefix="/api/v1", tags=["成绩学情归档审计"])

XLSX_DOWNLOAD_RESPONSE = {
    200: {
        "description": "XLSX 电子表格下载",
        "content": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                "schema": {"type": "string", "format": "binary"},
            },
        },
    }
}
CSV_DOWNLOAD_RESPONSE = {
    200: {
        "description": "CSV 审计表格下载",
        "content": {
            "text/csv": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}
ARCHIVE_ARTIFACT_DOWNLOAD_RESPONSE = {
    200: {
        "description": "经完整性校验的课程归档制品下载；实际 Content-Type 由归档制品登记决定",
        "content": {
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


def svc(session, user, request):
    return GradingService(session, user, request.state.request_id, request.client.host if request.client else "unknown")


@router.post("/grading/events/consume", response_model=EventConsumptionResponse, response_model_exclude_none=True)
def consume(data: EventEnvelope, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).consume(data)


@router.get("/grading/policies/{course_id}", response_model=GradingPolicyResponse, response_model_exclude_none=True)
def get_policy(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).get_policy(course_id)


@router.put("/grading/policies/{course_id}", response_model=GradingPolicyResponse, response_model_exclude_none=True)
def put_policy(course_id: str, data: PolicyInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    values={key:getattr(data,key) for key in ["attendance","assignment","quiz","lab","interaction"]};return svc(session,user,request).put_policy(course_id,values,data.effective_at)


@router.post("/grading/courses/{course_id}/recalculate", response_model=GradebookStateResponse, response_model_exclude_none=True)
def recalculate(course_id: str, data: RecalculateInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).recalculate(course_id,data.class_id)


@router.post("/grading/courses/{course_id}/post", response_model=GradebookStateResponse, response_model_exclude_none=True)
def post(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).post(course_id,class_id)


@router.get("/gradebook/courses/{course_id}", response_model=GradebookResponse, response_model_exclude_none=True)
def gradebook(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).gradebook(course_id,class_id)


@router.get("/gradebook/courses/{course_id}/students/{student_id}", response_model=GradebookResponse, response_model_exclude_none=True)
def student_grade(course_id: str, student_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).gradebook(course_id,class_id,student_id)


@router.get("/gradebook/courses/{course_id}/trace/{student_id}", response_model=GradebookTraceResponse, response_model_exclude_none=True)
def trace(course_id: str, student_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).trace(course_id,class_id,student_id)


@router.get(
    "/gradebook/courses/{course_id}/export.xlsx",
    response_class=StreamingResponse,
    responses=XLSX_DOWNLOAD_RESPONSE,
)
def gradebook_export(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    data=svc(session,user,request).gradebook_xlsx(course_id,class_id);return StreamingResponse(BytesIO(data),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=gradebook.xlsx"})


@router.get("/analytics/courses/{course_id}/overview", response_model=AnalyticsOverviewResponse, response_model_exclude_none=True)
def overview(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).overview(course_id,class_id)


@router.get("/analytics/courses/{course_id}/sections/{lesson_id}", response_model=AnalyticsSectionResponse, response_model_exclude_none=True)
def section(course_id: str, lesson_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).section(course_id,class_id,lesson_id)


@router.get("/analytics/courses/{course_id}/labs/by-student", response_model=AnalyticsStudentLabListResponse)
def labs_student(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).labs_by_student(course_id,class_id)


@router.get("/analytics/courses/{course_id}/labs/by-lab", response_model=AnalyticsLabListResponse)
def labs_lab(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).labs_by_lab(course_id,class_id)


@router.get("/analytics/courses/{course_id}/risks", response_model=StudentRiskListResponse)
def risks(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session), student_id: str | None = None): return svc(session,user,request).risks(course_id,class_id,student_id)


@router.get("/analytics/courses/{course_id}/learning-summary", response_model=LearningSummaryResponse, response_model_exclude_none=True)
def learning_summary(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session), student_id: str | None = None): return svc(session,user,request).learning_summary(course_id,class_id,student_id)


@router.get(
    "/analytics/courses/{course_id}/export.xlsx",
    response_class=StreamingResponse,
    responses=XLSX_DOWNLOAD_RESPONSE,
)
def analytics_export(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    data=svc(session,user,request).analytics_xlsx(course_id,class_id);return StreamingResponse(BytesIO(data),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=analytics.xlsx"})


@router.post("/archives/courses/{course_id}/precheck", response_model=ArchivePrecheckResponse)
def precheck(course_id: str, data: ArchiveInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).precheck(course_id,data.class_id)


@router.post("/archives/courses/{course_id}/freeze", response_model=ArchiveManifestPayloadResponse)
def archive_freeze(course_id: str, data: ArchiveInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).freeze_archive(course_id,data.class_id)


@router.get("/archives/courses/{course_id}", response_model=ArchiveResponse, response_model_exclude_none=True)
def archive_get(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).archive(course_id,class_id)


@router.get("/archives/courses/{course_id}/manifest", response_model=ArchiveManifestReadResponse, response_model_exclude_none=True)
def archive_manifest(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).archive(course_id,class_id).get("manifest") or {"status":"PENDING"}


@router.get(
    "/archives/courses/{course_id}/artifacts/{artifact_type}",
    response_class=Response,
    responses=ARCHIVE_ARTIFACT_DOWNLOAD_RESPONSE,
)
def archive_artifact(course_id: str, artifact_type: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    content,name,mime_type,digest=svc(session,user,request).artifact_download(course_id,class_id,artifact_type)
    return Response(content=content,media_type=mime_type,headers={"Content-Disposition":f"attachment; filename*=UTF-8''{quote(name)}","ETag":f'"{digest}"',"Cache-Control":"private, immutable"})


@router.get("/audit/events", response_model=AuditEventListResponse)
def audit_events(request: Request, user: CurrentUser, session: Session = Depends(get_session), course_id: str | None = None, action: str | None = None, result: str | None = None): return svc(session,user,request).audit_list(course_id,action,result)


@router.post("/audit/events/ingest", response_model=AuditIngestResponse)
def audit_ingest(data: AuditIngest, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).ingest_audit(data)


@router.get(
    "/audit/events/export.xlsx",
    response_class=StreamingResponse,
    responses=XLSX_DOWNLOAD_RESPONSE,
)
def audit_export_xlsx(request: Request, user: CurrentUser, session: Session = Depends(get_session), course_id: str | None = None):
    data=svc(session,user,request).audit_xlsx(course_id);return StreamingResponse(BytesIO(data),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=audit-events.xlsx"})


@router.get(
    "/audit/events/export.csv",
    response_class=Response,
    responses=CSV_DOWNLOAD_RESPONSE,
)
def audit_export_csv(request: Request, user: CurrentUser, session: Session = Depends(get_session), course_id: str | None = None): return Response(svc(session,user,request).audit_csv(course_id),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=audit-events.csv"})
