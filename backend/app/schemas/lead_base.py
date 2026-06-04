"""Pydantic schemas for lead bases."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.lead_base import LeadBaseSource


class LeadBaseCreate(BaseModel):
    campaign_id: UUID
    data_recebimento: date
    data_inicio: date | None = None
    data_fim: date | None = None
    channel_types: list[str] = Field(min_length=1)
    column_mapping: dict[str, str] = Field(default_factory=dict)


class LeadBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    data_recebimento: date
    data_inicio: date | None
    data_fim: date | None
    column_mapping: dict[str, Any]
    channel_types: list[str]
    leads_count: int
    source: LeadBaseSource = LeadBaseSource.MANUAL
    is_system: bool = False
    created_at: datetime


class LeadBaseListResponse(BaseModel):
    items: list[LeadBaseResponse]
    total: int
    skip: int
    limit: int


class LeadBaseColumnMappingUpdate(BaseModel):
    column_mapping: dict[str, str] = Field(default_factory=dict)


class DevolutivaFileResponse(BaseModel):
    data: str
    filename: str
    size_bytes: int
