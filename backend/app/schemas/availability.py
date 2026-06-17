"""Pydantic schemas for availability rules (weekly schedule)."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.activation_window import _parse_hhmm

_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


class AvailabilityDayInput(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0=segunda … 6=domingo")
    start_time: str = Field(min_length=5, max_length=5)
    end_time: str = Field(min_length=5, max_length=5)
    slot_minutes: int | None = Field(default=None, gt=0)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        raw = value.strip()
        if not _HHMM_RE.match(raw):
            raise ValueError("horário deve estar no formato HH:MM")
        try:
            _parse_hhmm(raw)
        except (ValueError, IndexError) as exc:
            raise ValueError("horário inválido") from exc
        return raw

    @model_validator(mode="after")
    def start_before_end(self) -> AvailabilityDayInput:
        if _parse_hhmm(self.start_time) >= _parse_hhmm(self.end_time):
            raise ValueError("start_time deve ser anterior a end_time")
        return self


class AvailabilityScheduleUpdate(BaseModel):
    days: list[AvailabilityDayInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_weekdays(self) -> AvailabilityScheduleUpdate:
        weekdays = [day.weekday for day in self.days]
        if len(weekdays) != len(set(weekdays)):
            raise ValueError("weekday duplicado na grade")
        return self


class AvailabilityRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    agent_id: UUID | None
    weekday: int
    start_time: str
    end_time: str
    slot_minutes: int | None
    timezone: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
