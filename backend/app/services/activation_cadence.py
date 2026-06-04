"""Camada C — cadência e tentativas do motor de acionamento (ACTIVE)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activation_cadence_text import CLOSE_DEVOLUTIVA, FOLLOWUP_ENQUEUED_MARKER
from app.core.activation_defaults import (
    MESSAGING_CHANNELS,
    VOICE_VIDEO_CHANNELS,
    channel_family,
    normalize_channel_type,
)
from app.services.activation_slots import release_slot_for_lead
from app.models.lead_interaction import LeadInteraction
from app.services.activation_service import get_agent_channel_settings_row, merged_params
from worker.tasks.conversation_routing import TERMINAL_STATUSES


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def lead_has_responded(record: LeadInteraction) -> bool:
    """
    Respondeu = inbound mais recente que o último outbound neste canal.
    data_ultimo_contato só é atualizado no inbound; data_ultima_tentativa no outbound.
    """
    last_inbound = _aware(record.data_ultimo_contato)
    last_outbound = _aware(record.data_ultima_tentativa) or _aware(record.data_acionamento)
    if last_outbound is None:
        return False
    if last_inbound is None:
        return False
    return last_inbound > last_outbound


def remaining_hourly_quota(limit: int, recent_count: int) -> int:
    return max(0, limit - recent_count)


async def resolve_channel_cadence_params(
    db: AsyncSession,
    agent_id: uuid.UUID,
    channel_type: str,
) -> dict:
    """Params mesclados com defaults por família de canal."""
    row = await get_agent_channel_settings_row(db, agent_id, channel_type)
    stored = row.params if row else None
    return merged_params(channel_type, stored)


async def count_recent_dispatches(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    channel_type: str,
    since: datetime,
) -> int:
    """Conta outbound na última hora para (campaign, channel) via data_ultima_tentativa."""
    channel = normalize_channel_type(channel_type)
    dispatch_ts = func.coalesce(
        LeadInteraction.data_ultima_tentativa,
        LeadInteraction.data_acionamento,
    )
    result = await session.execute(
        select(func.count())
        .select_from(LeadInteraction)
        .where(
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel,
            dispatch_ts.isnot(None),
            dispatch_ts >= since,
        )
    )
    return int(result.scalar_one())


def _non_terminal_filter():
    return LeadInteraction.status.notin_(tuple(TERMINAL_STATUSES))


async def leads_needing_followup(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    channel_type: str,
    minutos: int,
    max_tentativas: int,
) -> list[LeadInteraction]:
    channel = normalize_channel_type(channel_type)
    if channel not in MESSAGING_CHANNELS:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    result = await session.execute(
        select(LeadInteraction)
        .options(selectinload(LeadInteraction.lead))
        .where(
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel,
            _non_terminal_filter(),
            LeadInteraction.tentativas == 1,
            or_(
                LeadInteraction.devolutiva.is_(None),
                LeadInteraction.devolutiva != FOLLOWUP_ENQUEUED_MARKER,
            ),
            LeadInteraction.data_ultima_tentativa.isnot(None),
            LeadInteraction.data_ultima_tentativa <= cutoff,
        )
    )
    records = list(result.scalars().all())
    return [r for r in records if not lead_has_responded(r)]


async def leads_to_close_no_answer(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    channel_type: str,
    minutos: int,
    max_tentativas: int,
) -> list[LeadInteraction]:
    channel = normalize_channel_type(channel_type)
    if channel not in MESSAGING_CHANNELS:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    result = await session.execute(
        select(LeadInteraction)
        .where(
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel,
            _non_terminal_filter(),
            LeadInteraction.tentativas >= max_tentativas,
            LeadInteraction.data_ultima_tentativa.isnot(None),
            LeadInteraction.data_ultima_tentativa <= cutoff,
        )
    )
    records = list(result.scalars().all())
    return [r for r in records if not lead_has_responded(r)]


async def mark_followup_enqueued(session: AsyncSession, record: LeadInteraction) -> None:
    """Evita reenfileirar o mesmo follow-up antes do worker processar."""
    record.devolutiva = FOLLOWUP_ENQUEUED_MARKER
    await session.flush()


async def close_lead_no_answer(
    session: AsyncSession,
    record: LeadInteraction,
) -> None:
    record.status = "nao_atendido"
    record.devolutiva = CLOSE_DEVOLUTIVA
    await session.flush()
    release_slot_for_lead(str(record.lead_id), record.channel_type)


def is_voice_video_channel(channel_type: str) -> bool:
    return normalize_channel_type(channel_type) in VOICE_VIDEO_CHANNELS


def is_messaging_channel(channel_type: str) -> bool:
    return normalize_channel_type(channel_type) in MESSAGING_CHANNELS


def cadence_family(channel_type: str) -> str:
    return channel_family(channel_type)
