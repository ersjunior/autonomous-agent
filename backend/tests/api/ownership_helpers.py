"""Helpers compartilhados — recursos de outro dono via db_session (evita conflito de override)."""

from __future__ import annotations

import uuid

from app.models.channel import Channel, ChannelType
from app.models.tabulacao import Tabulacao
from tests.integration.helpers import OwnerContext, create_owner_context


async def foreign_owner_context(db_session, *, suffix: str | None = None) -> OwnerContext:
    return await create_owner_context(db_session, email_suffix=suffix or uuid.uuid4().hex[:8])


async def foreign_agent_id(db_session) -> uuid.UUID:
    ctx = await foreign_owner_context(db_session, suffix="foreign-agent")
    return ctx.agent.id


async def foreign_campaign_id(db_session) -> uuid.UUID:
    ctx = await foreign_owner_context(db_session, suffix="foreign-campaign")
    return ctx.campaign.id


async def foreign_lead_id(db_session) -> uuid.UUID:
    ctx = await foreign_owner_context(db_session, suffix="foreign-lead")
    return ctx.lead.id


async def foreign_channel_id(db_session) -> uuid.UUID:
    ctx = await foreign_owner_context(db_session, suffix="foreign-channel")
    channel = Channel(
        user_id=ctx.user.id,
        name=f"Foreign_{ctx.user.email[:6]}",
        type=ChannelType.WHATSAPP,
        credentials={},
        is_active=True,
    )
    db_session.add(channel)
    await db_session.flush()
    return channel.id


async def foreign_tabulacao_id(db_session) -> uuid.UUID:
    ctx = await foreign_owner_context(db_session, suffix="foreign-tab")
    tab = Tabulacao(
        user_id=ctx.user.id,
        nome="Tabulação Estrangeira",
        codigo=f"FOREIGN:{uuid.uuid4().hex[:6].upper()}",
        categoria="CUSTOMIZADO",
        is_terminal=False,
        is_system=False,
    )
    db_session.add(tab)
    await db_session.flush()
    return tab.id
