"""Schemas for monitoring attendance history and conversation threads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AttendanceHistoryItem(BaseModel):
    lead_interaction_id: UUID | None = None
    contact_user_id: str
    lead_nome: str | None = None
    campaign_id: UUID | None = None
    campaign_name: str | None = None
    channel: str
    status: str | None = None
    tabulacao_codigo: str | None = None
    tabulacao_nome: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    duration_available: bool = True
    message_count: int = 0
    last_message_preview: str | None = None
    has_lead: bool = False


class AttendanceHistoryListResponse(BaseModel):
    items: list[AttendanceHistoryItem]
    total: int
    skip: int
    limit: int


class ConversationMessage(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str
    at: datetime
    intent: str | None = None


class AttendanceConversationResponse(BaseModel):
    lead_interaction_id: UUID | None = None
    contact_user_id: str
    channel: str
    lead_nome: str | None = None
    campaign_name: str | None = None
    status: str | None = None
    tabulacao_codigo: str | None = None
    tabulacao_nome: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    duration_available: bool = True
    voice_partial_transcript: bool = False
    voice_duration_note: str | None = None
    messages: list[ConversationMessage]
