from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int, details: dict[str, Any] | None = None):
        self.code, self.message, self.status_code, self.details = code, message, status_code, details or {}


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"code": error.code, "message": error.message, "request_id": request.state.request_id, "details": error.details})


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"code": "REQUEST.VALIDATION_FAILED", "message": "请求参数校验失败", "request_id": request.state.request_id, "details": {"errors": jsonable_encoder(error.errors())}})
