import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.common.errors import ApiError
from app.database import SessionLocal, get_session
from app.runtime.schemas import (
    RuntimeBulkActionResponse,
    RuntimeInstanceDetailResponse,
    RuntimeReleaseStudentResponse,
    RuntimeRequestResponse,
    RuntimeSignalActionResponse,
    RuntimeTerminalTokenResponse,
)

from .gateway import GatewayBundle, get_gateways
from .models import ClassroomRuntimeEvent
from .schemas import (
    ClassroomLearningSummaryResponse,
    ClassroomReleaseStudentListResponse,
    ClassroomReleaseEventResponse,
    ClassroomReleaseSummaryResponse,
    ClassroomRuntimeEventConsumptionResponse,
    ClassroomStudentRuntimeResponse,
    DistributionCreate,
    LogDownloadResponse,
    RuntimeActionIn,
    RuntimeEventIn,
    StudentLogAssignmentListResponse,
    TeachingAuditLogListResponse,
    TeachingLogDistributionListResponse,
    TeachingLogDistributionResponse,
    TrafficLogListResponse,
)
from .service import ClassroomService, entity_dict

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]
Gateways = Annotated[GatewayBundle, Depends(get_gateways)]


def svc(db: Db, user: CurrentUser, gateways: Gateways) -> ClassroomService: return ClassroomService(db, user, gateways)


@router.get("/classroom/lab-releases/{release_id}/summary", response_model=ClassroomReleaseSummaryResponse, response_model_exclude_none=True)
def release_summary(release_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).release_summary(release_id)
@router.get("/classroom/lab-releases/{release_id}/students", response_model=ClassroomReleaseStudentListResponse, response_model_exclude_unset=True)
def release_students(release_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).release_students(release_id)
@router.get("/classroom/lab-releases/{release_id}/students/{student_id}", response_model=ClassroomStudentRuntimeResponse, response_model_exclude_unset=True)
def release_student(release_id: str, student_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).release_student(release_id, student_id)


@router.post(
    "/classroom/runtime/{runtime_id}/{action}",
    response_model=RuntimeInstanceDetailResponse | RuntimeSignalActionResponse,
    response_model_exclude_none=True,
)
def runtime_action(runtime_id: str, action: str, body: RuntimeActionIn, db: Db, user: CurrentUser, gateways: Gateways):
    if action not in {"remind","rejudge","extend","unlock","rebuild","destroy"}: raise ApiError("REQUEST.NOT_FOUND", "操作不存在", 404)
    return svc(db,user,gateways).runtime_action(runtime_id, action, body)


@router.post("/classroom/lab-releases/{release_id}/{action}", response_model=RuntimeBulkActionResponse)
def release_action(release_id: str, action: str, body: RuntimeActionIn, db: Db, user: CurrentUser, gateways: Gateways):
    if action not in {"extend-all","remind-idle"}: raise ApiError("REQUEST.NOT_FOUND", "操作不存在", 404)
    return svc(db,user,gateways).release_action(release_id, action, body)


@router.post("/classroom/my/lab-releases/{release_id}/start", response_model=RuntimeRequestResponse, response_model_exclude_none=True)
def student_start(release_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).student_start(release_id)
@router.get("/classroom/my/lab-releases/{release_id}", response_model=ClassroomStudentRuntimeResponse, response_model_exclude_unset=True)
def student_release(release_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).student_release(release_id)
@router.post(
    "/classroom/my/lab-releases/{release_id}/submit",
    response_model=RuntimeReleaseStudentResponse,
    response_model_exclude_none=True,
)
def student_submit(release_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).student_submit(release_id)
@router.get("/classroom/my/runtime/{runtime_id}/terminal-token", response_model=RuntimeTerminalTokenResponse)
def student_terminal(runtime_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).terminal_token(runtime_id, False)
@router.get("/classroom/runtime/{runtime_id}/terminal-token", response_model=RuntimeTerminalTokenResponse)
def teacher_terminal(runtime_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).terminal_token(runtime_id, True)


@router.get("/teaching-logs/audit", response_model=TeachingAuditLogListResponse)
def audit_logs(db: Db, user: CurrentUser, gateways: Gateways, class_id: str = "", lab_release_id: str = ""): return svc(db,user,gateways).audit_logs({"class_id":class_id,"lab_release_id":lab_release_id})
@router.get("/teaching-logs/traffic", response_model=TrafficLogListResponse, response_model_exclude_none=True)
def traffic_logs(db: Db, user: CurrentUser, gateways: Gateways, class_id: str = "", lab_release_id: str = ""): return svc(db,user,gateways).traffic_logs({"class_id":class_id,"lab_release_id":lab_release_id})
@router.get("/teaching-logs/traffic/{artifact_id}/download", response_model=LogDownloadResponse, response_model_exclude_none=True)
def traffic_download(artifact_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).artifact_download(artifact_id)
@router.post("/teaching-logs/distributions", status_code=201, response_model=TeachingLogDistributionResponse, response_model_exclude_none=True)
def create_distribution(body: DistributionCreate, db: Db, user: CurrentUser, gateways: Gateways, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None): return svc(db,user,gateways).create_distribution(body, idempotency_key or "")
@router.get("/teaching-logs/distributions", response_model=TeachingLogDistributionListResponse, response_model_exclude_none=True)
def distributions(db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).distributions()
@router.get("/teaching-logs/distributions/{distribution_id}", response_model=TeachingLogDistributionResponse, response_model_exclude_none=True)
def distribution(distribution_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).distribution(distribution_id)
@router.get("/teaching-logs/my-assignments", response_model=StudentLogAssignmentListResponse, response_model_exclude_none=True)
def my_assignments(db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).my_assignments()
@router.get("/teaching-logs/my-assignments/{assignment_id}/download", response_model=LogDownloadResponse, response_model_exclude_none=True)
def assignment_download(assignment_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).assignment_download(assignment_id)


@router.post("/classroom/events/runtime", response_model=ClassroomRuntimeEventConsumptionResponse)
def consume_runtime_event(body: RuntimeEventIn, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).consume_event(body)
@router.get("/classroom/read-model/students/{student_id}/learning-summary", response_model=ClassroomLearningSummaryResponse, response_model_exclude_none=True)
def learning_summary(student_id: str, class_id: str, db: Db, user: CurrentUser, gateways: Gateways): return svc(db,user,gateways).learning_summary(student_id, class_id)


@router.get(
    "/classroom/lab-releases/{release_id}/events",
    response_class=StreamingResponse,
    response_model=ClassroomReleaseEventResponse,
    responses={
        200: {
            "description": "实验发布运行事件流；每个 data 载荷符合 ClassroomReleaseEventResponse",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/ClassroomReleaseEventResponse"},
                }
            },
        }
    },
)
def release_events(release_id: str, db: Db, user: CurrentUser, gateways: Gateways, cursor: int = Query(0, ge=0), once: bool = False):
    svc(db,user,gateways).release_summary(release_id)
    async def stream():
        current = cursor
        while True:
            with SessionLocal() as event_db:
                rows = list(event_db.scalars(select(ClassroomRuntimeEvent).where(ClassroomRuntimeEvent.lab_release_id == release_id, ClassroomRuntimeEvent.event_sequence > current).order_by(ClassroomRuntimeEvent.event_sequence).limit(100)))
            for row in rows:
                current = row.event_sequence
                yield f"id: {current}\nevent: {row.event_type}\ndata: {json.dumps(entity_dict(row), ensure_ascii=False, default=str)}\n\n"
            if once: break
            if not rows: yield ": heartbeat\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
