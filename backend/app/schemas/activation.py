"""Pydantic schemas for agent channel settings and campaign activations."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_hhmm(value: str) -> str:
    if not _TIME_RE.match(value):
        raise ValueError("Horário deve estar no formato HH:MM (00:00–23:59)")
    return value


class VoiceVideoParams(BaseModel):
    chamadas_simultaneas: int = Field(ge=1, default=1)
    campanhas_simultaneas: int = Field(ge=1, default=1)
    tentativas_por_hora: int = Field(ge=0, default=6)
    horario_inicio: str = "09:00"
    horario_fim: str = "20:00"

    @field_validator("horario_inicio", "horario_fim")
    @classmethod
    def validate_time(cls, value: str) -> str:
        return _validate_hhmm(value)


class MessagingParams(BaseModel):
    chats_simultaneos: int = Field(ge=1, default=5)
    campanhas_simultaneas: int = Field(ge=1, default=1)
    tentativas_sem_resposta: int = Field(ge=0, default=2)
    minutos_segunda_mensagem: int = Field(ge=0, default=20)
    horario_inicio: str = "09:00"
    horario_fim: str = "20:00"
    receptivo_horario_inicio: str = "00:00"
    receptivo_horario_fim: str = "23:59"

    @field_validator(
        "horario_inicio",
        "horario_fim",
        "receptivo_horario_inicio",
        "receptivo_horario_fim",
    )
    @classmethod
    def validate_time(cls, value: str) -> str:
        return _validate_hhmm(value)


class ChannelSettingsResponse(BaseModel):
    agent_id: UUID
    channel_type: str
    params: dict[str, Any]
    is_system: bool
    editable: bool


class ChannelSettingsListResponse(BaseModel):
    agent_id: UUID
    is_system: bool
    editable: bool
    channels: list[ChannelSettingsResponse]


class ChannelSettingsUpdate(BaseModel):
    params: dict[str, Any]

    @model_validator(mode="after")
    def params_not_empty(self) -> ChannelSettingsUpdate:
        if not self.params:
            raise ValueError("params não pode ser vazio")
        return self


class ActivationResponse(BaseModel):
    agent_id: UUID
    campaign_id: UUID
    channel_type: str
    is_running: bool
    started_at: datetime | None = None
    stopped_at: datetime | None = None


class ActivationListResponse(BaseModel):
    campaign_id: UUID
    agent_id: UUID
    activations: list[ActivationResponse]


class ActivationStartResponse(BaseModel):
    status: Literal["started"] = "started"
    channel_type: str
    leads_dispatched: int
    dispatched_now: int = 0
    reason: str | None = None
    activation: ActivationResponse
