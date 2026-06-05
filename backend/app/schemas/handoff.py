"""Schemas — modo humano (handoff)."""

from datetime import datetime

from pydantic import BaseModel, Field


class HandoffContact(BaseModel):
    channel: str
    user_id: str
    lead_name: str | None = None
    escalated_at: datetime | None = None
    human_assumed_at: datetime | None = None
    assumed_by: str | None = None
    is_assumed: bool = False
    ttl_seconds: int | None = None


class HandoffChannelUserRequest(BaseModel):
    channel: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)


class HandoffReactivateRequest(HandoffChannelUserRequest):
    pass


class HandoffAssumeRequest(HandoffChannelUserRequest):
    pass


class HandoffFinalizeRequest(HandoffChannelUserRequest):
    tabulacao_codigo: str = Field(..., min_length=1)
    status_interno: str | None = None


class HandoffActionResponse(BaseModel):
    ok: bool
    channel: str
    user_id: str
    message: str | None = None


class HandoffReactivateResponse(BaseModel):
    reactivated: bool
    channel: str
    user_id: str
