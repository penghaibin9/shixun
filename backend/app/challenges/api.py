from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.context import CurrentUser
from app.labs.database import get_session

from .schemas import ChallengeAttemptResponse, ChallengeBind, ChallengeCreate, ChallengeListResponse, ChallengeResponse, FlagConfigure, FlagConfiguredResponse, FlagSubmit, HintCreate, HintListResponse, HintResponse
from .service import ChallengeService


router = APIRouter(prefix="/api/v1", tags=["挑战训练"])
Db = Annotated[Session, Depends(get_session)]


def service(db: Session, user: CurrentUser) -> ChallengeService:
    return ChallengeService(db, user)


@router.get("/challenges", response_model=ChallengeListResponse)
def list_challenges(db: Db, user: CurrentUser, course_id: str | None = None):
    return service(db, user).list_challenges(course_id)


@router.get("/challenges/{challenge_id}", response_model=ChallengeResponse)
def get_challenge(challenge_id: str, db: Db, user: CurrentUser):
    return service(db, user).get_challenge(challenge_id)


@router.post("/challenges", status_code=201, response_model=ChallengeResponse)
def create_challenge(body: ChallengeCreate, db: Db, user: CurrentUser):
    return service(db, user).create_challenge(body)


@router.post("/challenges/{challenge_id}/bind", response_model=ChallengeResponse)
def bind_challenge(challenge_id: str, body: ChallengeBind, db: Db, user: CurrentUser):
    return service(db, user).bind(challenge_id, body)


@router.post("/challenges/{challenge_id}/hints", status_code=201, response_model=HintResponse)
def add_hint(challenge_id: str, body: HintCreate, db: Db, user: CurrentUser):
    return service(db, user).add_hint(challenge_id, body)


@router.get("/challenges/{challenge_id}/hints", response_model=HintListResponse)
def list_hints(challenge_id: str, db: Db, user: CurrentUser):
    return service(db, user).hints(challenge_id)


@router.put("/challenges/{challenge_id}/flag", response_model=FlagConfiguredResponse)
def configure_flag(challenge_id: str, body: FlagConfigure, db: Db, user: CurrentUser):
    return service(db, user).configure_flag(challenge_id, body)


@router.post("/challenges/{challenge_id}/publish", response_model=ChallengeResponse)
def publish_challenge(challenge_id: str, db: Db, user: CurrentUser):
    return service(db, user).publish(challenge_id)


@router.post("/challenges/{challenge_id}/submit", response_model=ChallengeAttemptResponse)
def submit_flag(challenge_id: str, body: FlagSubmit, db: Db, user: CurrentUser):
    return service(db, user).submit(challenge_id, body)
