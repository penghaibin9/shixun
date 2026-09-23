from typing import Literal

from pydantic import BaseModel, ConfigDict


class IntegrationResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutboxDispatchItemResponse(IntegrationResponseModel):
    event_id: str
    event_type: str
    status: Literal["PUBLISHED", "FAILED"]
    targets: list[str]
    code: str | None = None
    message: str | None = None


class OutboxDispatchResponse(IntegrationResponseModel):
    selected: int
    published: int
    failed: int
    results: list[OutboxDispatchItemResponse]
