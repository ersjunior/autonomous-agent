"""Pydantic schemas for campaigns."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    agent_id: UUID
    channel_types: list[str] = Field(min_length=1)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    agent_id: UUID | None = None
    channel_types: list[str] | None = None
    status: str | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    name: str
    status: str
    channel_types: list[str]
    leads_count: int
    created_at: datetime


class CampaignStartResponse(BaseModel):
    status: str
    leads_dispatched: int
