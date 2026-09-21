from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int, details: dict[str, Any] | None = None):
        self.code, self.message, self.status_code, self.details = code, message, status_code, details or {}


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"code": error.code, "message": error.message, "request_id": request.state.request_id, "details": error.details})
