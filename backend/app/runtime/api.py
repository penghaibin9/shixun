import asyncio
from hashlib import sha256
from os import getenv
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
import websockets

from app.common.context import CurrentUser, UserContext
from app.common.errors import ApiError
from app.labs.database import create_session_factory, get_session

from . import models
from .catalog import LabCatalogClient
from .schemas import (
    ArtifactBundleRequest,
    DistributionBundleAuthorization,
    ImageRegister,
    NodeRegister,
    ReleaseContextInput,
    ReleaseStudentInput,
    RuntimeAction,
    RuntimeArtifactBundleResponse,
    RuntimeArtifactDetailResponse,
    RuntimeArtifactDownloadResponse,
    RuntimeArtifactListResponse,
    RuntimeAuditLogListResponse,
    RuntimeBulkActionResponse,
    RuntimeClassReadModelResponse,
    RuntimeEventListResponse,
    RuntimeExtend,
    RuntimeFacadeAction,
    RuntimeHeartbeatResult,
    RuntimeImageListResponse,
    RuntimeImageResponse,
    RuntimeInstanceDetailResponse,
    RuntimeInstanceListResponse,
    RuntimeLogListResponse,
    RuntimeMaintenanceResult,
    RuntimeMaintenanceRun,
    RuntimeNodeListResponse,
    RuntimeNodeResponse,
    RuntimeOverviewResponse,
    RuntimeQueueListResponse,
    RuntimeQueueRetryResult,
    RuntimeReleaseStudentsResponse,
    RuntimeReleaseStudentResponse,
    RuntimeReleaseSummaryResponse,
    RuntimeRequestResponse,
    RuntimeSignalActionResponse,
    RuntimeStart,
    RuntimeStudentReadModelResponse,
    RuntimeTerminalTokenResponse,
    RuntimeTrafficArtifactListResponse,
    TerminalTokenInput,
)
from .service import RuntimeService, new_id, now

router = APIRouter(prefix="/api/v1", tags=["实验运行时"])
DbSession = Annotated[Session, Depends(get_session)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=255)]
RuntimeId = Annotated[str, Path(min_length=1, max_length=36)]


def service(request: Request, session: Session, user: UserContext) -> RuntimeService:
    if request.headers.get("X-Service-Origin") == "lab-classroom":
        mapping = {
            "classroom.release.read": {"runtime.read"}, "classroom.lab.read": {"runtime.read"},
            "classroom.lab.start": {"runtime.start", "runtime.read"}, "classroom.lab.submit": {"runtime.submit", "runtime.read"},
            "classroom.runtime.destroy": {"runtime.destroy", "runtime.read"}, "classroom.runtime.rebuild": {"runtime.rebuild", "runtime.read"},
            "classroom.runtime.extend": {"runtime.extend", "runtime.read"}, "classroom.runtime.rejudge": {"runtime.rejudge", "runtime.read"},
            "classroom.runtime.remind": {"runtime.remind", "runtime.read"}, "classroom.runtime.unlock": {"runtime.unlock", "runtime.read"},
            "classroom.terminal.use": {"runtime.terminal", "runtime.read"}, "classroom.terminal.assist": {"runtime.terminal", "runtime.read"},
            "classroom.logs.read": {"runtime.read"}, "classroom.logs.download": {"runtime.read"},
            "classroom.logs.assignment.download": {"runtime.distributed-artifact.download"},
            "classroom.release.extend-all": {"runtime.extend", "runtime.read"}, "classroom.release.remind-idle": {"runtime.remind", "runtime.read"},
        }
        permissions = set(user.permissions)
        for source, target in mapping.items():
            if source in user.permissions:
                permissions.update(target)
        user = UserContext(user.user_id, user.role, user.teacher_id, user.student_id, frozenset(permissions), user.course_ids, user.class_ids)
    catalog = getattr(request.app.state, "runtime_catalog", None)
    agent_factory = getattr(request.app.state, "runtime_agent_factory", None)
    return RuntimeService(session, user, catalog=catalog, agent_factory=agent_factory)


@router.post(
    "/runtime/start",
    status_code=201,
    response_model=RuntimeRequestResponse,
    responses={202: {"model": RuntimeRequestResponse}},
)
async def start_runtime(data: RuntimeStart, request: Request, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    result = await service(request, session, user).start(data, idempotency_key)
    return JSONResponse(result, status_code=202 if result["status"] == "QUEUED" else 201)


@router.post(
    "/runtime/preview-requests",
    status_code=201,
    response_model=RuntimeRequestResponse,
    responses={202: {"model": RuntimeRequestResponse}},
)
async def preview_runtime(data: RuntimeStart, request: Request, session: DbSession, authorization: Annotated[str | None, Header()] = None):
    expected = getenv("YUEKE_INTERNAL_RUNTIME_TOKEN")
    if not expected or authorization != f"Bearer {expected}":
        raise ApiError("AUTH.SERVICE_UNAUTHENTICATED", "实验定义服务身份校验失败", 401)
    if data.mode != "TEACHER_PREVIEW" or not data.requested_by or not data.idempotency_key:
        raise ApiError("RUNTIME.INVALID_PREVIEW_REQUEST", "预演请求字段不完整", 422)
    user = UserContext(data.requested_by, "teacher", data.requested_by, None, frozenset({"runtime.preview", "runtime.read"}), frozenset({data.course_id} if data.course_id else set()), frozenset({data.class_id} if data.class_id else set()))
    return await service(request, session, user).start(data, data.idempotency_key)


@router.post("/runtime/release-contexts", response_model=RuntimeReleaseSummaryResponse)
async def register_release_context(data: ReleaseContextInput, request: Request, session: DbSession, authorization: Annotated[str | None, Header()] = None):
    expected = getenv("YUEKE_INTERNAL_RUNTIME_TOKEN")
    if not expected or authorization != f"Bearer {expected}":
        raise ApiError("AUTH.SERVICE_UNAUTHENTICATED", "实验发布事件来源校验失败", 401)
    user = UserContext("service_lab_definition", "admin", None, None, frozenset({"runtime.read"}), frozenset({data.course_id}), frozenset({data.class_id}))
    return await service(request, session, user).register_release_context(release_id=data.lab_release_id, version_id=data.lab_version_id, course_id=data.course_id, class_id=data.class_id, status=data.status)


@router.get("/runtime/requests/{request_id}", response_model=RuntimeRequestResponse)
def get_request(request_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).request(request_id)


@router.post("/runtime/requests/{request_id}/cancel", response_model=RuntimeRequestResponse)
def cancel_request(request_id: str, data: RuntimeAction, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).cancel_request(request_id, data.reason)


@router.get("/runtime-instances/{instance_id}", response_model=RuntimeInstanceDetailResponse)
def get_instance(instance_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).instance(instance_id)


@router.post("/runtime-instances/{instance_id}/destroy", response_model=RuntimeInstanceDetailResponse)
async def destroy_instance(instance_id: str, data: RuntimeAction, request: Request, session: DbSession, user: CurrentUser):
    return await service(request, session, user).destroy(instance_id, data.reason)


@router.post("/runtime-instances/{instance_id}/rebuild", response_model=RuntimeInstanceDetailResponse)
async def rebuild_instance(instance_id: str, data: RuntimeAction, request: Request, session: DbSession, user: CurrentUser):
    return await service(request, session, user).rebuild(instance_id, data.reason)


@router.post("/runtime-instances/{instance_id}/extend", response_model=RuntimeInstanceDetailResponse)
def extend_instance(instance_id: str, data: RuntimeExtend, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).extend(instance_id, data)


@router.post("/runtime-instances/{instance_id}/rejudge", response_model=RuntimeInstanceDetailResponse)
async def rejudge_instance(instance_id: str, request: Request, session: DbSession, user: CurrentUser):
    return await service(request, session, user).rejudge(instance_id)


@router.get("/runtime-instances/{instance_id}/logs", response_model=RuntimeLogListResponse)
def instance_logs(instance_id: str, request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).logs(instance_id)
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.get("/runtime-instances/{instance_id}/traffic-artifacts", response_model=RuntimeArtifactListResponse)
def traffic_artifacts(instance_id: str, request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).artifacts(instance_id)
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/runtime-instances/{instance_id}/terminal-token", response_model=RuntimeTerminalTokenResponse)
def issue_terminal_token(instance_id: str, data: TerminalTokenInput, request: Request, session: DbSession, user: CurrentUser):
    result = service(request, session, user).terminal_token(instance_id, data.idle_timeout_seconds)
    result["websocket_url"] = getenv("YUEKE_PUBLIC_RUNTIME_WS_URL", "") + result["websocket_path"]
    result["expires_in"] = min(data.idle_timeout_seconds, 300)
    result["token_transport"] = "FIRST_FRAME"
    return result


@router.get("/infrastructure/nodes", response_model=RuntimeNodeListResponse)
def list_nodes(request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).nodes()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/infrastructure/nodes", status_code=201, response_model=RuntimeNodeResponse)
async def register_node(data: NodeRegister, request: Request, session: DbSession, user: CurrentUser):
    return await service(request, session, user).register_node(data)


@router.post("/infrastructure/nodes/{node_id}/heartbeat", response_model=RuntimeHeartbeatResult)
async def refresh_node_heartbeat(node_id: RuntimeId, request: Request, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return await service(request, session, user).refresh_node_heartbeat(node_id, idempotency_key)


@router.get("/infrastructure/images", response_model=RuntimeImageListResponse)
def list_images(request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).images()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/infrastructure/images", status_code=201, response_model=RuntimeImageResponse)
def register_image(data: ImageRegister, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).register_image(data)


@router.get("/infrastructure/queue", response_model=RuntimeQueueListResponse)
def list_queue(request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).queue()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/infrastructure/queue/{queue_id}/retry", response_model=RuntimeQueueRetryResult)
async def retry_queue_item(queue_id: RuntimeId, request: Request, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return await service(request, session, user).retry_queue(queue_id, idempotency_key)


@router.post("/infrastructure/maintenance/run", response_model=RuntimeMaintenanceResult, response_model_exclude_none=True)
async def run_runtime_maintenance(data: RuntimeMaintenanceRun, request: Request, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return await service(request, session, user).run_maintenance(data, idempotency_key)


@router.get("/infrastructure/overview", response_model=RuntimeOverviewResponse)
def infrastructure_overview(request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).infrastructure_overview()


@router.get("/infrastructure/events", response_model=RuntimeEventListResponse)
def infrastructure_events(request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).recent_events()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.get("/runtime-instances", response_model=RuntimeInstanceListResponse)
def list_instances(request: Request, session: DbSession, user: CurrentUser):
    items = service(request, session, user).instances()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.get("/runtime/read-model/classes/{class_id}", response_model=RuntimeClassReadModelResponse)
def class_runtime_read_model(class_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).class_read_model(class_id)


@router.get("/runtime/read-model/students/{student_id}", response_model=RuntimeStudentReadModelResponse)
def student_runtime_read_model(student_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).student_read_model(student_id)


# E 课堂线兼容 façade：保留 D 的冻结资源路由，同时消除跨线拼装字段。
@router.get("/runtime/lab-releases/{release_id}/summary", response_model=RuntimeReleaseSummaryResponse)
def release_summary(release_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).release_summary(release_id)


@router.get("/runtime/lab-releases/{release_id}/students", response_model=RuntimeReleaseStudentsResponse)
def release_students(release_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).release_students(release_id)


@router.get("/runtime/lab-releases/{release_id}/students/{student_id}", response_model=RuntimeReleaseStudentResponse)
def release_student(release_id: str, student_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).release_student(release_id, student_id)


@router.get("/runtime/lab-releases/{release_id}", response_model=RuntimeReleaseSummaryResponse)
def release_detail(release_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).release_summary(release_id)


@router.post(
    "/runtime/lab-releases/{release_id}/start",
    status_code=201,
    response_model=RuntimeRequestResponse,
    responses={202: {"model": RuntimeRequestResponse}},
)
async def release_start(release_id: str, data: ReleaseStudentInput, request: Request, session: DbSession, user: CurrentUser):
    result = await service(request, session, user).start_release(release_id, data.student_id)
    return JSONResponse(result, status_code=202 if result["status"] == "QUEUED" else 201)


@router.post(
    "/runtime/lab-releases/{release_id}/submit",
    response_model=RuntimeReleaseStudentResponse,
)
def release_submit(release_id: str, data: ReleaseStudentInput, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).submit_release(release_id, data.student_id, data.runtime_instance_id)


@router.post("/runtime/lab-releases/{release_id}/{action}", response_model=RuntimeBulkActionResponse)
def release_bulk_action(release_id: str, action: str, data: RuntimeFacadeAction, request: Request, session: DbSession, user: CurrentUser):
    runtime = service(request, session, user)
    if action not in {"extend-all", "remind-idle"}:
        raise ApiError("REQUEST.NOT_FOUND", "操作不存在", 404)
    students = runtime.release_students(release_id)["items"]
    changed = 0
    for item in students:
        instance_id = item.get("runtime_instance_id")
        if not instance_id or item.get("status") != "RUNNING":
            continue
        if action == "extend-all":
            runtime.extend(instance_id, RuntimeExtend(minutes=data.minutes or 10, reason=data.reason or "课堂统一延时"))
        else:
            runtime.signal_action(instance_id, "remind", data.reason)
        changed += 1
    return {"lab_release_id": release_id, "action": action, "affected": changed, "status": "ACCEPTED"}


@router.get("/runtime/instances/{instance_id}", response_model=RuntimeInstanceDetailResponse)
def facade_instance(instance_id: str, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).instance(instance_id)


@router.post("/runtime/instances/{instance_id}/terminal-token", response_model=RuntimeTerminalTokenResponse)
def facade_terminal_token(instance_id: str, data: TerminalTokenInput, request: Request, session: DbSession, user: CurrentUser):
    return issue_terminal_token(instance_id, data, request, session, user)


@router.post(
    "/runtime/instances/{instance_id}/{action}",
    response_model=RuntimeInstanceDetailResponse | RuntimeSignalActionResponse,
)
async def facade_instance_action(instance_id: str, action: str, data: RuntimeFacadeAction, request: Request, session: DbSession, user: CurrentUser):
    runtime = service(request, session, user)
    if action == "destroy": return await runtime.destroy(instance_id, data.reason or "课堂销毁")
    if action == "rebuild": return await runtime.rebuild(instance_id, data.reason or "课堂重建")
    if action == "extend": return runtime.extend(instance_id, RuntimeExtend(minutes=data.minutes or 10, reason=data.reason or "课堂延时"))
    if action == "rejudge": return await runtime.rejudge(instance_id)
    if action in {"remind", "unlock"}: return runtime.signal_action(instance_id, action, data.reason)
    raise ApiError("REQUEST.NOT_FOUND", "操作不存在", 404)


@router.get("/runtime/logs/audit", response_model=RuntimeAuditLogListResponse)
def audit_log_query(request: Request, session: DbSession, user: CurrentUser, class_id: str = "", lab_release_id: str = "", student_id: str = ""):
    return service(request, session, user).runtime_logs(class_id=class_id, release_id=lab_release_id, student_id=student_id)


@router.get("/runtime/logs/traffic", response_model=RuntimeTrafficArtifactListResponse)
def traffic_log_query(request: Request, session: DbSession, user: CurrentUser, class_id: str = "", lab_release_id: str = "", student_id: str = ""):
    return service(request, session, user).traffic_logs(class_id=class_id, release_id=lab_release_id, student_id=student_id)


@router.get("/runtime/log-artifacts/{artifact_id}", response_model=RuntimeArtifactDetailResponse)
def artifact_detail(artifact_id: str, request: Request, session: DbSession, user: CurrentUser):
    runtime = service(request, session, user)
    runtime._permission("runtime.read")
    artifact = session.get(models.RuntimeArtifact, artifact_id)
    if not artifact:
        raise ApiError("RUNTIME.ARTIFACT_NOT_FOUND", "日志制品不存在", 404)
    instance = session.get(models.RuntimeInstance, artifact.runtime_instance_id)
    runtime._instance_scope(instance)
    group = session.get(models.RuntimeInstanceGroup, instance.runtime_group_id)
    source = session.get(models.RuntimeRequest, group.runtime_request_id)
    return {"artifact_id": artifact_id, "file_id": artifact.file_id, "sha256": artifact.sha256, "size_bytes": artifact.size_bytes, "student_id": source.student_id, "lab_release_id": source.lab_release_id, "course_id": source.course_id, "class_id": source.class_id}


@router.post("/runtime/log-artifacts/{artifact_id}/download-url", response_model=RuntimeArtifactDownloadResponse)
def artifact_download_url(artifact_id: str, request: Request, session: DbSession, user: CurrentUser):
    result = service(request, session, user).direct_artifact_bundle([artifact_id])
    return {"artifact_id": artifact_id, **result}


@router.post("/runtime/log-artifacts/bundle-url", response_model=RuntimeArtifactBundleResponse)
def artifact_bundle_url(data: ArtifactBundleRequest, request: Request, session: DbSession, user: CurrentUser):
    return service(request, session, user).direct_artifact_bundle(data.artifact_ids)


@router.post("/runtime/log-artifacts/distribution-bundle-url", response_model=RuntimeArtifactBundleResponse)
def distribution_artifact_bundle_url(
    data: DistributionBundleAuthorization,
    request: Request,
    session: DbSession,
    user: CurrentUser,
    service_origin: Annotated[str | None, Header(alias="X-Service-Origin")] = None,
):
    if service_origin != "lab-classroom":
        raise ApiError("AUTH.SERVICE_ORIGIN_REQUIRED", "日志分发下载只接受实验课堂服务调用", 403)
    return service(request, session, user).distribution_artifact_bundle(data.authorization)


@router.get(
    "/artifact-storage/bundles/{assignment_id}",
    response_class=FileResponse,
    responses={200: {"description": "日志任务 ZIP 压缩包", "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}},
)
def download_artifact_bundle(
    assignment_id: str,
    request: Request,
    session: DbSession,
    user: CurrentUser,
    capability: Annotated[str, Query(min_length=40, max_length=32768)],
):
    path = service(request, session, user).download_artifact_bundle(assignment_id, capability)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"logs-{assignment_id}.zip",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.websocket("/runtime-instances/{instance_id}/terminal")
async def terminal_socket(websocket: WebSocket, instance_id: str):
    """Token 必须作为首帧发送，避免出现在 URL、历史记录和访问日志。"""
    await websocket.accept()
    try:
        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        except asyncio.TimeoutError:
            await websocket.close(code=4408, reason="终端认证首帧超时")
            return
        raw = first.get("token", "")
        if not raw:
            await websocket.close(code=4401, reason="缺少终端令牌")
            return
        session_factory = create_session_factory()()
        try:
            terminal = session_factory.scalar(select(models.RuntimeTerminalSession).where(models.RuntimeTerminalSession.token_hash == sha256(raw.encode()).hexdigest(), models.RuntimeTerminalSession.runtime_instance_id == instance_id).with_for_update())
            instance = session_factory.get(models.RuntimeInstance, instance_id)
            if not terminal or not instance or terminal.status != "ISSUED" or terminal.expires_at <= now() or instance.status != "RUNNING" or instance.role != "STUDENT_WORKSTATION":
                await websocket.close(code=4403, reason="终端令牌无效或已过期")
                return
            group = session_factory.get(models.RuntimeInstanceGroup, instance.runtime_group_id)
            node = session_factory.get(models.InfraNode, group.node_id) if group else None
            if not group or not node or not group.provider_group_id:
                await websocket.close(code=1013, reason="节点终端桥接不可用")
                return
            terminal.status, terminal.last_seen_at = "CONNECTED", now()
            session_factory.add(models.RuntimeEvent(runtime_event_id=new_id("rte"), runtime_instance_id=instance_id, runtime_group_id=instance.runtime_group_id, event_type="runtime.terminal.connected", actor_user_id=terminal.user_id, detail_json={"terminal_session_id": terminal.terminal_session_id}, occurred_at=now()))
            session_factory.commit()
            agent_ws = node.agent_url.replace("https://", "wss://").replace("http://", "ws://") + f"/runtime-groups/{group.provider_group_id}/terminal/{instance.node_key}"
            agent_token = getenv("YUEKE_NODE_AGENT_TOKEN")
            if not agent_token:
                await websocket.close(code=1013, reason="节点代理身份凭据未配置")
                return
            async with websockets.connect(agent_ws, additional_headers={"Authorization": f"Bearer {agent_token}"}, open_timeout=5) as upstream:
                await websocket.send_json({"type": "ready"})
                loop = asyncio.get_running_loop()
                idle_seconds = max((terminal.expires_at - terminal.created_at).total_seconds(), 30)
                last_activity = loop.time()

                async def receive_with_idle(receive):
                    nonlocal last_activity
                    while True:
                        remaining = idle_seconds - (loop.time() - last_activity)
                        if remaining <= 0:
                            raise asyncio.TimeoutError
                        try:
                            value = await asyncio.wait_for(receive(), timeout=min(remaining, 5))
                            last_activity = loop.time()
                            terminal.last_seen_at = now()
                            return value
                        except asyncio.TimeoutError:
                            if loop.time() - last_activity >= idle_seconds:
                                raise

                async def browser_to_agent():
                    while True:
                        message = await receive_with_idle(websocket.receive)
                        if message.get("type") == "websocket.disconnect":
                            raise WebSocketDisconnect(message.get("code", 1000))
                        if message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                        elif message.get("text") is not None:
                            await upstream.send(message["text"])

                async def agent_to_browser():
                    while True:
                        message = await receive_with_idle(upstream.recv)
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = {asyncio.create_task(browser_to_agent()), asyncio.create_task(agent_to_browser())}
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
        except asyncio.TimeoutError:
            await websocket.close(code=4408, reason="终端空闲超时")
        except (WebSocketDisconnect, websockets.WebSocketException):
            return
        finally:
            if "terminal" in locals() and terminal:
                terminal.status, terminal.last_seen_at = "CLOSED", now()
                session_factory.add(models.RuntimeEvent(runtime_event_id=new_id("rte"), runtime_instance_id=instance_id, runtime_group_id=instance.runtime_group_id if "instance" in locals() and instance else None, event_type="runtime.terminal.closed", actor_user_id=terminal.user_id, detail_json={"terminal_session_id": terminal.terminal_session_id}, occurred_at=now()))
                session_factory.commit()
            session_factory.close()
    except WebSocketDisconnect:
        return
