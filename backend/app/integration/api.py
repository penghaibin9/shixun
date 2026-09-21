from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session

from .service import OutboxDispatcher


router = APIRouter(prefix="/api/v1/integration", tags=["跨域契约集成"])


@router.post("/outbox/dispatch")
async def dispatch_outbox(request: Request, user: CurrentUser, limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
    return await OutboxDispatcher(session, user, request.state.request_id).dispatch(limit)
