"""Pydantic schemas for channels."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.channel import ChannelType


class ChannelCreate(BaseModel):
    name: str | None = None
    type: ChannelType
    credentials: dict[str, Any] = {}
    is_active: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = None
    type: ChannelType | None = None
    credentials: dict[str, Any] | None = None
    is_active: bool | None = None


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None = None
    type: ChannelType
    credentials: dict[str, Any]
    is_active: bool
    is_system: bool = False
    created_at: datetime
