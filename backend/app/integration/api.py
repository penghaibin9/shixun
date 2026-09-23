from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session

from .schemas import OutboxDispatchResponse
from .service import OutboxDispatcher


router = APIRouter(prefix="/api/v1/integration", tags=["跨域契约集成"])


@router.post("/outbox/dispatch", response_model=OutboxDispatchResponse, response_model_exclude_none=True)
async def dispatch_outbox(request: Request, user: CurrentUser, limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
    return await OutboxDispatcher(session, user, request.state.request_id).dispatch(limit)
