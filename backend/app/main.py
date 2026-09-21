from uuid import uuid4

from fastapi import FastAPI, Request

from .common.context import CurrentUser
from .common.errors import ApiError, api_error_handler
from .labs.api import router as labs_router
from .runtime.api import router as runtime_router

app = FastAPI(title="跃科网络空间安全实训平台 API", version="1.0.0", openapi_url="/api/v1/openapi.json")
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(labs_router)
app.include_router(runtime_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-Id", f"req_{uuid4().hex}")
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/auth/context")
async def auth_context(user: CurrentUser) -> dict:
    return {"user_id": user.user_id, "role": user.role, "teacher_id": user.teacher_id, "student_id": user.student_id, "permissions": sorted(user.permissions), "course_ids": sorted(user.course_ids), "class_ids": sorted(user.class_ids)}
