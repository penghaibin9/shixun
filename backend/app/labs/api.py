from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.common.context import CurrentUser, UserContext

from .database import get_session
from .schemas import CloneVersionInput, KnowledgeInput, LabCreate, LabDefinitionListResponse, LabDefinitionResponse, LabDefinitionSpec, LabKnowledgeListResponse, LabKnowledgeResponse, LabReleasePreflightResponse, LabReleaseResponse, LabTeacherPreviewResponse, LabTemplateListResponse, LabTemplateResponse, LabVersionPatch, LabVersionResponse, ReleaseCreate, TemplateCreate
from .service import LabService

router = APIRouter(prefix="/api/v1", tags=["实验定义"])
DbSession = Annotated[Session, Depends(get_session)]
IdempotencyKey = Annotated[str, Header(alias="X-Idempotency-Key", min_length=8, max_length=255)]

DIAGRAM_DOWNLOAD_RESPONSE = {
    200: {
        "description": "实验讲解图二进制文件；实际 Content-Type 由已登记的文件类型决定",
        "content": {
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


def service(session: Session, user: UserContext) -> LabService:
    return LabService(session, user)


@router.get("/labs", response_model=LabDefinitionListResponse)
def list_labs(session: DbSession, user: CurrentUser):
    items = service(session, user).list_labs()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/labs", status_code=201, response_model=LabDefinitionResponse)
def create_lab(data: LabCreate, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).create_lab(data, idempotency_key)


@router.post("/labs/import", status_code=201, response_model=LabDefinitionResponse)
async def import_lab(
    session: DbSession,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    file: UploadFile = File(...),
    course_id: str = Form(..., min_length=1, max_length=36),
    code: str = Form(..., min_length=1, max_length=64),
    category: str = Form(..., min_length=1, max_length=64),
    objective: str = Form(..., min_length=1, max_length=4000),
):
    content = await file.read(1024 * 1024 + 1)
    return service(session, user).import_lab(
        course_id=course_id,
        code=code,
        category=category,
        objective=objective,
        content=content,
        idempotency_key=idempotency_key,
    )


@router.get("/labs/{definition_id}", response_model=LabDefinitionResponse)
def get_lab(definition_id: str, session: DbSession, user: CurrentUser):
    return service(session, user).get_lab(definition_id)


@router.post("/labs/{definition_id}/versions", status_code=201, response_model=LabVersionResponse)
def clone_version(definition_id: str, data: CloneVersionInput, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).clone_version(definition_id, data, idempotency_key)


@router.get("/lab-versions/{version_id}", response_model=LabVersionResponse)
def get_version(version_id: str, session: DbSession, user: CurrentUser):
    return service(session, user).get_version(version_id)


@router.patch("/lab-versions/{version_id}", response_model=LabVersionResponse)
def patch_version(version_id: str, data: LabVersionPatch, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).patch_version(version_id, data, idempotency_key)


@router.post("/lab-versions/{version_id}/validate", response_model=LabVersionResponse)
def validate_version(version_id: str, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).validate_version(version_id, idempotency_key)


@router.post("/lab-versions/{version_id}/publish", response_model=LabVersionResponse)
def publish_version(version_id: str, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).publish_version(version_id, idempotency_key)


@router.get("/lab-versions/{version_id}/export.json", response_model=LabDefinitionSpec)
def export_version(version_id: str, session: DbSession, user: CurrentUser):
    version = service(session, user).get_version(version_id)
    return JSONResponse(version["spec"], headers={"Content-Disposition": f'attachment; filename="{version["lab_definition_id"]}-v{version["version"]}.json"'})


@router.get("/lab-templates", response_model=LabTemplateListResponse)
def list_templates(session: DbSession, user: CurrentUser):
    items = service(session, user).templates()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/lab-templates", status_code=201, response_model=LabTemplateResponse)
def create_template(data: TemplateCreate, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).create_template(data, idempotency_key)


@router.get("/lab-knowledge", response_model=LabKnowledgeListResponse)
def list_knowledge(session: DbSession, user: CurrentUser):
    items = service(session, user).knowledge()
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/lab-knowledge", status_code=201, response_model=LabKnowledgeResponse)
def create_knowledge(data: KnowledgeInput, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).create_knowledge(data, idempotency_key)


@router.patch("/lab-knowledge/{knowledge_id}", response_model=LabKnowledgeResponse)
def patch_knowledge(knowledge_id: str, data: KnowledgeInput, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).patch_knowledge(knowledge_id, data, idempotency_key)


@router.get(
    "/lab-knowledge/{knowledge_id}/diagrams/{diagram_id}/download",
    response_class=FileResponse,
    responses=DIAGRAM_DOWNLOAD_RESPONSE,
)
def download_diagram(knowledge_id: str, diagram_id: str, session: DbSession, user: CurrentUser):
    path, filename, media_type = service(session, user).diagram_download(knowledge_id, diagram_id)
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post("/lab-releases", status_code=201, response_model=LabReleaseResponse)
def create_release(data: ReleaseCreate, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).create_release(data, idempotency_key)


@router.post("/lab-releases/{release_id}/preflight", response_model=LabReleasePreflightResponse)
def preflight_release(release_id: str, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).preflight_release(release_id, idempotency_key)


@router.post("/lab-releases/{release_id}/teacher-preview", response_model=LabTeacherPreviewResponse)
async def teacher_preview(release_id: str, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return await service(session, user).teacher_preview(release_id, idempotency_key)


@router.post("/lab-releases/{release_id}/publish", response_model=LabReleaseResponse)
def publish_release(release_id: str, session: DbSession, user: CurrentUser, idempotency_key: IdempotencyKey):
    return service(session, user).publish_release(release_id, idempotency_key)
