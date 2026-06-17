"""Pydantic schemas for appointments."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AppointmentStatusLiteral = Literal[
    "SCHEDULED",
    "CONFIRMED",
    "CANCELLED",
    "COMPLETED",
    "NO_SHOW",
]

AppointmentSourceLiteral = Literal["AGENT", "MANUAL"]

VALID_STATUSES: frozenset[str] = frozenset(
    {"SCHEDULED", "CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"}
)


class AppointmentCreate(BaseModel):
    lead_id: UUID
    starts_at: datetime
    ends_at: datetime
    title: str = Field(min_length=1, max_length=255)
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title não pode ser vazio")
        return stripped


class AppointmentUpdate(BaseModel):
    status: AppointmentStatusLiteral | None = None
    notes: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def status_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in VALID_STATUSES:
            raise ValueError("status inválido")
        return value


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    lead_id: UUID
    lead_name: str | None = None
    agent_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    title: str
    notes: str | None
    status: str
    created_by: str
    channel: str | None
    created_at: datetime
    updated_at: datetime
