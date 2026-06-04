"""Channel CRUD and webhook API routes."""

import re
import uuid
import xml.sax.saxutils
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.channels.whatsapp.handler import WhatsAppHandler
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.channel import Channel
from app.models.user import User
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate

router = APIRouter(prefix="/channels", tags=["channels"])
whatsapp = WhatsAppHandler()

UUID_MP3_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.mp3$",
    re.IGNORECASE,
)
UUID_MP4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.mp4$",
    re.IGNORECASE,
)


def _build_voice_outbound_say_twiml(text: str) -> str:
    """TwiML fallback com <Say> (voz Twilio Polly)."""
    spoken = xml.sax.saxutils.escape((text or "").strip() or " ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Say language="pt-BR" voice="Polly.Camila">{spoken}</Say>\n'
        "</Response>"
    )


def _build_voice_outbound_play_twiml(filename: str) -> str:
    """TwiML fase 2 (b): <Play> com MP3 Coqui servido pelo backend."""
    if not UUID_MP3_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid audio filename")

    base = settings.require_public_base_url()
    play_url = xml.sax.saxutils.escape(
        f"{base}/api/v1/channels/webhooks/voice/audio/{filename}"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"  <Play>{play_url}</Play>\n"
        "</Response>"
    )


async def _get_channel(
    channel_id: uuid.UUID, user: User, db: AsyncSession
) -> Channel:
    result = await db.execute(
        select(Channel).where(Channel.id == channel_id, Channel.user_id == user.id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@router.get("/", response_model=list[ChannelResponse])
async def list_channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Channel]:
    result = await db.execute(select(Channel).where(Channel.user_id == user.id))
    return list(result.scalars().all())


@router.post("/", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Channel:
    channel = Channel(
        user_id=user.id,
        type=payload.type,
        credentials=payload.credentials,
        is_active=payload.is_active,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Channel:
    return await _get_channel(channel_id, user, db)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Channel:
    channel = await _get_channel(channel_id, user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    channel = await _get_channel(channel_id, user, db)
    await db.delete(channel)
    await db.commit()


@router.get("/webhooks/voice/audio/{filename}")
async def voice_audio_file(filename: str):
    """Serve MP3 gerado pelo worker para Twilio <Play>."""
    if not UUID_MP3_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = Path(settings.voice_audio_root) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")

    return FileResponse(path, media_type="audio/mpeg", filename=filename)


@router.get("/avatar-video/{filename}")
async def avatar_video_file(filename: str):
    """Serve MP4 gerado pelo SadTalker (preview / integrações por URL)."""
    if not UUID_MP4_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = Path(settings.avatar_video_root) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")

    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/webhooks/voice/outbound")
@router.post("/webhooks/voice/outbound")
async def voice_outbound_webhook(
    text: str = Query("", description="Texto a ser falado na chamada (fallback <Say>)"),
):
    """TwiML fallback com voz sintética Twilio."""
    twiml = _build_voice_outbound_say_twiml(text)
    return Response(content=twiml, media_type="application/xml")


@router.get("/webhooks/voice/outbound-audio")
@router.post("/webhooks/voice/outbound-audio")
async def voice_outbound_audio_webhook(
    audio: str = Query("", description="Nome do arquivo MP3 (UUID.mp3) gerado pelo Coqui"),
):
    """TwiML principal fase 2 (b): reproduz MP3 com voz clonada Coqui."""
    twiml = _build_voice_outbound_play_twiml(audio)
    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
):
    twiml = await whatsapp.handle_webhook({"Body": Body, "From": From, "To": To})
    return Response(content=twiml, media_type="application/xml")
