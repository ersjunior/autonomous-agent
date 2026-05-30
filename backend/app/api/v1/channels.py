"""Channel CRUD and webhook API routes."""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.channels.whatsapp.handler import WhatsAppHandler
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.channel import Channel
from app.models.user import User
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate

router = APIRouter(prefix="/channels", tags=["channels"])
whatsapp = WhatsAppHandler()


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


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
):
    twiml = await whatsapp.handle_webhook({"Body": Body, "From": From, "To": To})
    return Response(content=twiml, media_type="application/xml")
