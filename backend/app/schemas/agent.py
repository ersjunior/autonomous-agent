"""Pydantic schemas for agents."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentMode


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    mode: AgentMode
    config: dict[str, Any] = {}


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    mode: AgentMode | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    mode: AgentMode
    status: str
    config: dict[str, Any]
    created_at: datetime
