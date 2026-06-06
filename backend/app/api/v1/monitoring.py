"""Real-time monitoring WebSocket and attendance history endpoints."""

from __future__ import annotations

import asyncio
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from agents.events import AGENT_EVENTS_CHANNEL
from app.api.v1.campaigns import _get_campaign
from app.core.activation_defaults import SUPPORTED_CHANNEL_TYPES, normalize_channel_type
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.monitoring_attendance import (
    AttendanceConversationResponse,
    AttendanceHistoryListResponse,
)
from app.services.attendance_history import (
    ATTENDANCE_STATUS_VALUES,
    get_attendance_conversation_by_contact,
    get_attendance_conversation_by_li,
    list_attendance_history,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class ConnectionManager:
    """Manages active WebSocket connections and Redis pub/sub listener."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._listener_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._redis_listener())

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def _redis_listener(self) -> None:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(AGENT_EVENTS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self.broadcast(message["data"])
        finally:
            await pubsub.unsubscribe(AGENT_EVENTS_CHANNEL)
            await pubsub.aclose()
            await client.aclose()


manager = ConnectionManager()


@router.websocket("/ws")
async def monitoring_ws(websocket: WebSocket) -> None:
    """WebSocket feed of agent events from Redis pub/sub."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def _validate_channel_type_param(channel_type: str) -> str:
    normalized = normalize_channel_type(channel_type)
    if normalized not in SUPPORTED_CHANNEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel type: {channel_type}",
        )
    return normalized


@router.get("/attendance-history", response_model=AttendanceHistoryListResponse)
async def get_attendance_history(
    skip: int = 0,
    limit: int = 50,
    campaign_id: uuid.UUID | None = None,
    channel_type: str | None = None,
    status: str | None = None,
    open_only: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttendanceHistoryListResponse:
    """
    Histórico híbrido de atendimentos (supervisão/QA).

    Inclui LeadInteractions com atividade conversacional e contatos receptivos órfãos
    (sem LI). Não exige ``data_acionamento`` — inbound puro entra aqui.
    """
    if skip < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="skip must be >= 0")
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200",
        )

    normalized_channel: str | None = None
    if channel_type is not None and channel_type.strip():
        normalized_channel = _validate_channel_type_param(channel_type)

    normalized_status: str | None = None
    if status is not None and status.strip():
        normalized_status = status.strip().lower()
        if normalized_status not in ATTENDANCE_STATUS_VALUES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of: {', '.join(ATTENDANCE_STATUS_VALUES)}",
            )

    if campaign_id is not None:
        await _get_campaign(campaign_id, user, db)

    items, total = await list_attendance_history(
        db,
        user,
        skip=skip,
        limit=limit,
        campaign_id=campaign_id,
        channel_type=normalized_channel,
        status_filter=normalized_status,
        open_only=open_only,
    )
    return AttendanceHistoryListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/attendance/{lead_interaction_id}/messages",
    response_model=AttendanceConversationResponse,
)
async def get_attendance_messages_by_li(
    lead_interaction_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttendanceConversationResponse:
    """Thread cronológica de mensagens para um LeadInteraction."""
    return await get_attendance_conversation_by_li(db, lead_interaction_id, user)


@router.get("/contact-messages", response_model=AttendanceConversationResponse)
async def get_attendance_messages_by_contact(
    channel: str = Query(..., min_length=1),
    contact_user_id: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttendanceConversationResponse:
    """Thread para contato órfão (sem LeadInteraction) — somente leitura."""
    normalized = _validate_channel_type_param(channel)
    return await get_attendance_conversation_by_contact(
        db,
        user,
        normalized,
        contact_user_id,
    )
