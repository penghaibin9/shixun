from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi

from .common.context import CurrentUser, UserContextResponse
from .common.errors import ApiError, api_error_handler, validation_error_handler
from .grading.api import router as grading_router
from .integration.api import router as integration_router
from .lab_classroom.api import router as classroom_router
from .labs.api import router as labs_router
from .resources.api import router as resources_router
from .teaching.api import router as teaching_router
from .runtime.api import router as runtime_router

app = FastAPI(title="跃科网络空间安全实训平台 API", version="1.0.0", openapi_url="/api/v1/openapi.json")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(teaching_router)
app.include_router(resources_router)
app.include_router(labs_router)
app.include_router(runtime_router)
app.include_router(classroom_router)
app.include_router(grading_router)
app.include_router(integration_router)


def frozen_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes, openapi_version=app.openapi_version)
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas["Error"] = {
        "type": "object",
        "required": ["code", "message", "request_id", "details"],
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "request_id": {"type": "string"},
            "details": {"type": "object", "additionalProperties": True},
        },
    }
    error_response = {"description": "标准错误信封", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            responses = operation.setdefault("responses", {})
            responses.setdefault("401", error_response)
            responses.setdefault("403", error_response)
            responses["422"] = error_response
    app.openapi_schema = schema
    return schema


app.openapi = frozen_openapi


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-Id", f"req_{uuid4().hex}")
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/auth/context", response_model=UserContextResponse)
async def auth_context(user: CurrentUser) -> UserContextResponse:
    return UserContextResponse(user_id=user.user_id, role=user.role, teacher_id=user.teacher_id, student_id=user.student_id, permissions=sorted(user.permissions), course_ids=sorted(user.course_ids), class_ids=sorted(user.class_ids))
