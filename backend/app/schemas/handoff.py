"""Schemas — modo humano (handoff)."""

from datetime import datetime

from pydantic import BaseModel, Field


class HandoffContact(BaseModel):
    channel: str
    user_id: str
    escalated_at: datetime | None = None
    ttl_seconds: int | None = None


class HandoffReactivateRequest(BaseModel):
    channel: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)


class HandoffReactivateResponse(BaseModel):
    reactivated: bool
    channel: str
    user_id: str
