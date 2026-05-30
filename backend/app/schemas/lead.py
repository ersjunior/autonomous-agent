"""Pydantic schemas for leads."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = None
    email: str | None = None
    extra_data: dict[str, Any] = {}


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = None
    email: str | None = None
    extra_data: dict[str, Any] | None = None
    status: str | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str | None
    email: str | None
    extra_data: dict[str, Any]
    status: str
    created_at: datetime
