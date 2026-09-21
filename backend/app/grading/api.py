from io import BytesIO

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session
from .schemas import ArchiveInput, AuditIngest, EventEnvelope, PolicyInput, RecalculateInput
from .service import GradingService

router = APIRouter(prefix="/api/v1", tags=["成绩学情归档审计"])


def svc(session, user, request):
    return GradingService(session, user, request.state.request_id, request.client.host if request.client else "unknown")


@router.post("/grading/events/consume")
def consume(data: EventEnvelope, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).consume(data)


@router.get("/grading/policies/{course_id}")
def get_policy(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).get_policy(course_id)


@router.put("/grading/policies/{course_id}")
def put_policy(course_id: str, data: PolicyInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    values={key:getattr(data,key) for key in ["attendance","assignment","quiz","lab","interaction"]};return svc(session,user,request).put_policy(course_id,values,data.effective_at)


@router.post("/grading/courses/{course_id}/recalculate")
def recalculate(course_id: str, data: RecalculateInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).recalculate(course_id,data.class_id)


@router.post("/grading/courses/{course_id}/post")
def post(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).post(course_id)


@router.get("/gradebook/courses/{course_id}")
def gradebook(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).gradebook(course_id)


@router.get("/gradebook/courses/{course_id}/students/{student_id}")
def student_grade(course_id: str, student_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).gradebook(course_id,student_id)


@router.get("/gradebook/courses/{course_id}/trace/{student_id}")
def trace(course_id: str, student_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).trace(course_id,student_id)


@router.get("/gradebook/courses/{course_id}/export.xlsx")
def gradebook_export(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    data=svc(session,user,request).gradebook_xlsx(course_id);return StreamingResponse(BytesIO(data),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=gradebook.xlsx"})


@router.get("/analytics/courses/{course_id}/overview")
def overview(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).overview(course_id)


@router.get("/analytics/courses/{course_id}/sections/{lesson_id}")
def section(course_id: str, lesson_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).section(course_id,lesson_id)


@router.get("/analytics/courses/{course_id}/labs/by-student")
def labs_student(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).labs_by_student(course_id)


@router.get("/analytics/courses/{course_id}/labs/by-lab")
def labs_lab(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).labs_by_lab(course_id)


@router.get("/analytics/courses/{course_id}/risks")
def risks(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session), student_id: str | None = None): return svc(session,user,request).risks(course_id,student_id)


@router.get("/analytics/courses/{course_id}/learning-summary")
def learning_summary(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session), student_id: str | None = None): return svc(session,user,request).learning_summary(course_id,student_id)


@router.get("/analytics/courses/{course_id}/export.xlsx")
def analytics_export(course_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)):
    data=svc(session,user,request).analytics_xlsx(course_id);return StreamingResponse(BytesIO(data),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=analytics.xlsx"})


@router.post("/archives/courses/{course_id}/precheck")
def precheck(course_id: str, data: ArchiveInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).precheck(course_id,data.class_id)


@router.post("/archives/courses/{course_id}/freeze")
def archive_freeze(course_id: str, data: ArchiveInput, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).freeze_archive(course_id,data.class_id)


@router.get("/archives/courses/{course_id}")
def archive_get(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).archive(course_id,class_id)


@router.get("/archives/courses/{course_id}/manifest")
def archive_manifest(course_id: str, class_id: str, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).archive(course_id,class_id).get("manifest") or {"status":"PENDING"}


@router.get("/audit/events")
def audit_events(request: Request, user: CurrentUser, session: Session = Depends(get_session), course_id: str | None = None, action: str | None = None, result: str | None = None): return svc(session,user,request).audit_list(course_id,action,result)


@router.post("/audit/events/ingest")
def audit_ingest(data: AuditIngest, request: Request, user: CurrentUser, session: Session = Depends(get_session)): return svc(session,user,request).ingest_audit(data)


@router.get("/audit/events/export.xlsx")
def audit_export_xlsx(request: Request, user: CurrentUser, session: Session = Depends(get_session), course_id: str | None = None):
    data=svc(session,user,request).audit_xlsx(course_id);return StreamingResponse(BytesIO(data),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=audit-events.xlsx"})


@router.get("/audit/events/export.csv")
def audit_export_csv(request: Request, user: CurrentUser, session: Session = Depends(get_session), course_id: str | None = None): return Response(svc(session,user,request).audit_csv(course_id),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=audit-events.csv"})
