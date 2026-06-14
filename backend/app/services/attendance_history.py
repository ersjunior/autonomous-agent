"""Attendance history (monitoring) — hybrid LeadInteraction rows + orphan contacts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import can_view
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.models.user import User
from app.schemas.monitoring_attendance import (
    AttendanceConversationResponse,
    AttendanceHistoryItem,
    ConversationMessage,
)
from app.services.contact_normalization import (
    canonical_contact_ids,
    infer_channel_from_contact,
)
from worker.tasks.conversation_routing import (
    SEED_AGENT_RECEPTIVE_NAME,
    TERMINAL_STATUSES,
    get_latest_lead_interaction,
)
from worker.tasks.lead_tracking import find_lead_by_channel_user
from worker.tasks.outbound_campaign import _resolve_recipient

from app.core.activation_defaults import VOICE_CHANNELS
ATTENDANCE_STATUS_VALUES = (
    "pendente",
    "acionado",
    "em_andamento",
    "convertido",
    "recusou",
    "nao_atendido",
    "erro",
)
VOICE_DURATION_NOTE = (
    "Duração da chamada indisponível (integração de telefonia pendente). "
    "Exibida apenas transcrição parcial das falas processadas pelo agente."
)
PREVIEW_MAX_LEN = 120


@dataclass
class InteractionStats:
    message_count: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    last_preview: str | None = None


def campaign_visibility_filter(user: User):
    return or_(Campaign.is_system.is_(True), Campaign.user_id == user.id)


def _is_terminal_status(status_value: str | None) -> bool:
    return (status_value or "").lower() in TERMINAL_STATUSES


def _duration_available(channel: str) -> bool:
    return channel.lower() not in VOICE_CHANNELS


def _truncate_preview(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) <= PREVIEW_MAX_LEN:
        return cleaned
    return cleaned[: PREVIEW_MAX_LEN - 1] + "…"


async def get_receptive_pool_owner_id(db: AsyncSession) -> uuid.UUID | None:
    """Owner of the seed Agente_Receptivo (institutional receptive pool)."""
    result = await db.execute(
        select(Agent.user_id)
        .where(
            Agent.is_system.is_(True),
            Agent.mode == AgentMode.RECEPTIVE,
            Agent.name == SEED_AGENT_RECEPTIVE_NAME,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def can_view_orphan_attendance(user: User, receptive_owner_id: uuid.UUID | None) -> bool:
    """
    Orphan policy: interactions without LeadInteraction are attributed to the
    institutional receptive pool. Only the owner of Agente_Receptivo (seed admin)
    may list them — prevents cross-tenant leakage of unknown contacts.
    """
    if receptive_owner_id is None:
        return False
    return user.id == receptive_owner_id


async def fetch_interaction_stats(
    db: AsyncSession,
    contact_variants: list[str],
) -> InteractionStats:
    if not contact_variants:
        return InteractionStats()

    agg = await db.execute(
        select(
            func.count(Interaction.id),
            func.min(Interaction.created_at),
            func.max(Interaction.created_at),
        ).where(Interaction.user_id.in_(contact_variants))
    )
    count, first_at, last_at = agg.one()

    preview: str | None = None
    if count and count > 0:
        last_row = await db.execute(
            select(Interaction.message, Interaction.response)
            .where(Interaction.user_id.in_(contact_variants))
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )
        msg, resp = last_row.one()
        preview = _truncate_preview(resp or msg)

    return InteractionStats(
        message_count=int(count or 0),
        first_at=first_at,
        last_at=last_at,
        last_preview=preview,
    )


def _compute_timestamps(
    *,
    channel: str,
    li: LeadInteraction | None,
    stats: InteractionStats,
) -> tuple[datetime | None, datetime | None, int | None, bool]:
    started_candidates: list[datetime] = []
    if li and li.data_acionamento:
        started_candidates.append(li.data_acionamento)
    if stats.first_at:
        started_candidates.append(stats.first_at)
    if li and li.data_ultimo_contato and not started_candidates:
        started_candidates.append(li.data_ultimo_contato)
    if li and li.created_at and not started_candidates:
        started_candidates.append(li.created_at)

    started_at = min(started_candidates) if started_candidates else None

    ended_at: datetime | None = None
    if li and _is_terminal_status(li.status) and li.tabulacao_aplicada_em:
        ended_at = li.tabulacao_aplicada_em
    elif stats.last_at:
        ended_at = stats.last_at

    duration_available = _duration_available(channel)
    duration_seconds: int | None = None
    if duration_available and started_at and ended_at:
        duration_seconds = max(0, int((ended_at - started_at).total_seconds()))

    return started_at, ended_at, duration_seconds, duration_available


def _has_conversational_activity(li: LeadInteraction | None, stats: InteractionStats) -> bool:
    if stats.message_count > 0:
        return True
    if li is None:
        return False
    if li.data_ultimo_contato or li.data_acionamento:
        return True
    return _is_terminal_status(li.status)


def _li_to_item(
    li: LeadInteraction,
    *,
    contact_user_id: str,
    stats: InteractionStats,
) -> AttendanceHistoryItem:
    lead = li.lead
    campaign = li.campaign
    tab = li.tabulacao
    channel = li.channel_type
    started_at, ended_at, duration_seconds, duration_available = _compute_timestamps(
        channel=channel,
        li=li,
        stats=stats,
    )
    return AttendanceHistoryItem(
        lead_interaction_id=li.id,
        contact_user_id=contact_user_id,
        lead_nome=lead.nome_cliente if lead else None,
        campaign_id=li.campaign_id,
        campaign_name=campaign.name if campaign else None,
        channel=channel,
        status=li.status,
        tabulacao_codigo=tab.codigo if tab else None,
        tabulacao_nome=tab.nome if tab else None,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        duration_available=duration_available,
        message_count=stats.message_count,
        last_message_preview=stats.last_preview,
        has_lead=lead is not None,
    )


def _orphan_to_item(
    *,
    contact_user_id: str,
    channel: str,
    stats: InteractionStats,
    lead: Lead | None,
) -> AttendanceHistoryItem:
    started_at, ended_at, duration_seconds, duration_available = _compute_timestamps(
        channel=channel,
        li=None,
        stats=stats,
    )
    return AttendanceHistoryItem(
        lead_interaction_id=None,
        contact_user_id=contact_user_id,
        lead_nome=lead.nome_cliente if lead else None,
        campaign_id=None,
        campaign_name=None,
        channel=channel,
        status=None,
        tabulacao_codigo=None,
        tabulacao_nome=None,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        duration_available=duration_available,
        message_count=stats.message_count,
        last_message_preview=stats.last_preview,
        has_lead=lead is not None,
    )


def _apply_item_filters(
    item: AttendanceHistoryItem,
    *,
    campaign_id: uuid.UUID | None,
    channel_type: str | None,
    status_filter: str | None,
    open_only: bool,
) -> bool:
    if campaign_id is not None and item.campaign_id != campaign_id:
        return False
    if channel_type is not None and item.channel.lower() != channel_type.lower():
        return False
    if status_filter is not None:
        if item.status is None or item.status.lower() != status_filter.lower():
            return False
    if open_only and item.status is not None and _is_terminal_status(item.status):
        return False
    return True


async def _collect_li_items(
    db: AsyncSession,
    user: User,
) -> list[AttendanceHistoryItem]:
    result = await db.execute(
        select(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(campaign_visibility_filter(user))
        .options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign),
            selectinload(LeadInteraction.tabulacao),
        )
    )
    records = list(result.scalars().unique().all())
    items: list[AttendanceHistoryItem] = []
    for li in records:
        contact = _resolve_recipient(li.lead, li.channel_type) if li.lead else None
        if not contact:
            continue
        variants = canonical_contact_ids(li.channel_type, contact)
        stats = await fetch_interaction_stats(db, variants)
        if not _has_conversational_activity(li, stats):
            continue
        items.append(
            _li_to_item(li, contact_user_id=contact, stats=stats)
        )
    return items


async def _contact_has_tracked_li(
    db: AsyncSession,
    channel: str,
    user_id: str,
) -> bool:
    lead = await find_lead_by_channel_user(db, channel, user_id)
    if lead is None:
        return False
    li = await get_latest_lead_interaction(db, lead.id, channel)
    if li is None:
        return False
    variants = canonical_contact_ids(channel, user_id)
    stats = await fetch_interaction_stats(db, variants)
    return _has_conversational_activity(li, stats)


async def _collect_orphan_items(
    db: AsyncSession,
    user: User,
) -> list[AttendanceHistoryItem]:
    receptive_owner = await get_receptive_pool_owner_id(db)
    if not can_view_orphan_attendance(user, receptive_owner):
        return []

    distinct = await db.execute(select(Interaction.user_id).distinct())
    raw_ids = [row[0] for row in distinct.all() if row[0]]

    items: list[AttendanceHistoryItem] = []
    seen_keys: set[tuple[str, str]] = set()

    for raw_uid in raw_ids:
        channel = infer_channel_from_contact(raw_uid)
        if await _contact_has_tracked_li(db, channel, raw_uid):
            continue

        variants = canonical_contact_ids(channel, raw_uid)
        canonical_key = variants[0] if variants else raw_uid
        dedupe_key = (channel, canonical_key)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        stats = await fetch_interaction_stats(db, variants)
        if stats.message_count == 0:
            continue

        lead = await find_lead_by_channel_user(db, channel, raw_uid)
        display_contact = canonical_key
        items.append(
            _orphan_to_item(
                contact_user_id=display_contact,
                channel=channel,
                stats=stats,
                lead=lead,
            )
        )
    return items


async def list_attendance_history(
    db: AsyncSession,
    user: User,
    *,
    skip: int,
    limit: int,
    campaign_id: uuid.UUID | None = None,
    channel_type: str | None = None,
    status_filter: str | None = None,
    open_only: bool = False,
) -> tuple[list[AttendanceHistoryItem], int]:
    li_items = await _collect_li_items(db, user)
    orphan_items = await _collect_orphan_items(db, user)
    merged = li_items + orphan_items

    filtered = [
        item
        for item in merged
        if _apply_item_filters(
            item,
            campaign_id=campaign_id,
            channel_type=channel_type,
            status_filter=status_filter,
            open_only=open_only,
        )
    ]

    filtered.sort(
        key=lambda x: x.started_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    total = len(filtered)
    page = filtered[skip : skip + limit]
    return page, total


async def get_lead_interaction_for_attendance(
    db: AsyncSession,
    interaction_id: uuid.UUID,
    user: User,
) -> tuple[LeadInteraction, str]:
    result = await db.execute(
        select(LeadInteraction)
        .options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign),
            selectinload(LeadInteraction.tabulacao),
        )
        .where(LeadInteraction.id == interaction_id)
    )
    record = result.scalar_one_or_none()
    if record is None or record.campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Atendimento não encontrado",
        )
    if not can_view(record.campaign, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Atendimento não encontrado",
        )
    if record.lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado para este atendimento",
        )
    contact = _resolve_recipient(record.lead, record.channel_type)
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contato não disponível para este canal",
        )
    return record, contact


async def assert_orphan_contact_access(
    db: AsyncSession,
    user: User,
    channel: str,
    contact_user_id: str,
) -> None:
    receptive_owner = await get_receptive_pool_owner_id(db)
    if not can_view_orphan_attendance(user, receptive_owner):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada",
        )
    if await _contact_has_tracked_li(db, channel, contact_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use o endpoint por lead_interaction_id para este contato",
        )
    variants = canonical_contact_ids(channel, contact_user_id)
    stats = await fetch_interaction_stats(db, variants)
    if stats.message_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada",
        )


async def fetch_conversation_messages(
    db: AsyncSession,
    channel: str,
    contact_user_id: str,
) -> list[ConversationMessage]:
    variants = canonical_contact_ids(channel, contact_user_id)
    if not variants:
        return []

    result = await db.execute(
        select(Interaction)
        .where(Interaction.user_id.in_(variants))
        .order_by(Interaction.created_at.asc())
    )
    rows = list(result.scalars().all())

    messages: list[ConversationMessage] = []
    for row in rows:
        messages.append(
            ConversationMessage(
                role="user",
                content=row.message,
                at=row.created_at,
                intent=row.intent,
            )
        )
        messages.append(
            ConversationMessage(
                role="assistant",
                content=row.response,
                at=row.created_at,
            )
        )
    return messages


async def build_conversation_response(
    db: AsyncSession,
    *,
    channel: str,
    contact_user_id: str,
    li: LeadInteraction | None = None,
    lead: Lead | None = None,
) -> AttendanceConversationResponse:
    variants = canonical_contact_ids(channel, contact_user_id)
    stats = await fetch_interaction_stats(db, variants)
    messages = await fetch_conversation_messages(db, channel, contact_user_id)
    started_at, ended_at, duration_seconds, duration_available = _compute_timestamps(
        channel=channel,
        li=li,
        stats=stats,
    )
    tab = li.tabulacao if li else None
    campaign = li.campaign if li else None
    voice_partial = channel.lower() in VOICE_CHANNELS

    return AttendanceConversationResponse(
        lead_interaction_id=li.id if li else None,
        contact_user_id=contact_user_id,
        channel=channel,
        lead_nome=(li.lead.nome_cliente if li and li.lead else None) or (lead.nome_cliente if lead else None),
        campaign_name=campaign.name if campaign else None,
        status=li.status if li else None,
        tabulacao_codigo=tab.codigo if tab else None,
        tabulacao_nome=tab.nome if tab else None,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        duration_available=duration_available,
        voice_partial_transcript=voice_partial,
        voice_duration_note=VOICE_DURATION_NOTE if voice_partial else None,
        messages=messages,
    )


async def get_attendance_conversation_by_li(
    db: AsyncSession,
    interaction_id: uuid.UUID,
    user: User,
) -> AttendanceConversationResponse:
    li, contact = await get_lead_interaction_for_attendance(db, interaction_id, user)
    return await build_conversation_response(
        db,
        channel=li.channel_type,
        contact_user_id=contact,
        li=li,
        lead=li.lead,
    )


async def get_attendance_conversation_by_contact(
    db: AsyncSession,
    user: User,
    channel: str,
    contact_user_id: str,
) -> AttendanceConversationResponse:
    await assert_orphan_contact_access(db, user, channel, contact_user_id)
    lead = await find_lead_by_channel_user(db, channel, contact_user_id)
    return await build_conversation_response(
        db,
        channel=channel,
        contact_user_id=contact_user_id,
        li=None,
        lead=lead,
    )
