from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChallengeCreate(StrictModel):
    course_id: str = Field(min_length=1, max_length=36)
    lesson_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    difficulty: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = "BEGINNER"
    max_attempts: int = Field(default=10, ge=1, le=50)
    prerequisite_challenge_id: str | None = Field(default=None, max_length=36)


class ChallengeBind(StrictModel):
    lab_definition_id: str = Field(min_length=1, max_length=36)
    checkpoint_key: str = Field(min_length=2, max_length=64)


class HintCreate(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)
    unlock_after_attempts: int = Field(default=1, ge=0, le=50)


class FlagConfigure(StrictModel):
    flag: str = Field(min_length=4, max_length=256)
    case_sensitive: bool = True


class FlagSubmit(StrictModel):
    submission: str = Field(min_length=1, max_length=256)
    class_id: str = Field(min_length=1, max_length=36)
    lab_release_id: str | None = Field(default=None, max_length=36)


class ChallengeResponse(BaseModel):
    challenge_id: str
    course_id: str
    lesson_id: str
    lab_definition_id: str | None = None
    checkpoint_key: str | None = None
    prerequisite_challenge_id: str | None = None
    unlocked: bool = True
    title: str
    description: str
    difficulty: str
    max_attempts: int
    status: str
    flag_configured: bool
    created_by: str
    created_at: datetime
    published_at: datetime | None = None


class ChallengeListResponse(BaseModel):
    items: list[ChallengeResponse]
    page: int
    page_size: int
    total: int


class HintResponse(BaseModel):
    hint_id: str
    challenge_id: str
    sequence: int
    title: str
    content: str
    unlock_after_attempts: int


class HintListResponse(BaseModel):
    items: list[HintResponse]
    attempts: int
    total: int


class FlagConfiguredResponse(BaseModel):
    challenge_id: str
    configured: bool
    case_sensitive: bool


class ChallengeAttemptResponse(BaseModel):
    attempt_id: str
    challenge_id: str
    attempt_no: int
    accepted: bool
    remaining_attempts: int
    created_at: datetime
