from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.database import get_session

from .schemas import AccountCreate, AccountListResponse, AccountView, IdentityReconciliationScanResponse
from .service import AuthService


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_session)]


def service(db: Db, user: CurrentUser) -> AuthService:
    return AuthService(db, user)


@router.post("/users", status_code=201, response_model=AccountView)
def create_account(body: AccountCreate, db: Db, user: CurrentUser):
    return service(db, user).create_account(body)


@router.get("/users", response_model=AccountListResponse)
def list_accounts(
    db: Db,
    user: CurrentUser,
    search: str = "",
    role: Literal["admin", "teacher", "student"] | None = None,
    status: Literal["ACTIVE", "DISABLED"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return service(db, user).list_accounts(search=search, role=role, status=status, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=AccountView)
def get_account(user_id: str, db: Db, user: CurrentUser):
    return service(db, user).get_account(user_id)


@router.post("/reconciliation/scan", response_model=IdentityReconciliationScanResponse)
def scan_identity_reconciliation(db: Db, user: CurrentUser):
    return service(db, user).scan_identity_reconciliation()
