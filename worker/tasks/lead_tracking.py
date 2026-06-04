"""Shared helpers for lead interaction tracking."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.channels.phone import normalize_phone_digits as normalize_phone
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction

logger = logging.getLogger(__name__)

POSITIVE_INTENTS = frozenset({"purchase"})
REFUSAL_INTENTS = frozenset({"cancel"})


async def upsert_lead_interaction(
    session: AsyncSession,
    lead_id: uuid.UUID,
    campaign_id: uuid.UUID,
    channel_type: str,
    *,
    status: str | None = None,
    devolutiva: str | None = None,
    last_interaction_id: uuid.UUID | None = None,
    set_acionamento: bool = False,
) -> LeadInteraction:
    """Busca ou cria LeadInteraction por (lead_id, campaign_id, channel_type). Não commita."""
    channel = channel_type.lower()
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(LeadInteraction).where(
            LeadInteraction.lead_id == lead_id,
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        record = LeadInteraction(
            lead_id=lead_id,
            campaign_id=campaign_id,
            channel_type=channel,
            status=status or "pendente",
        )
        session.add(record)

    if status is not None:
        record.status = status
    if devolutiva is not None:
        record.devolutiva = devolutiva
    if last_interaction_id is not None:
        record.last_interaction_id = last_interaction_id
    if set_acionamento:
        record.data_acionamento = now

    record.data_ultimo_contato = now
    await session.flush()
    return record


def _digits_only(column):
    return func.regexp_replace(column, r"[^0-9]", "", "g")


async def find_lead_by_channel_user(
    session: AsyncSession,
    channel: str,
    user_id: str,
) -> Lead | None:
    """Identifica lead pelo identificador do canal (telefone ou telegram_id)."""
    channel_lower = channel.lower()

    if channel_lower in ("whatsapp", "voice"):
        normalized_user = normalize_phone(user_id)
        if not normalized_user:
            return None

        result = await session.execute(
            select(Lead)
            .options(selectinload(Lead.lead_base))
            .where(
                or_(
                    _digits_only(Lead.telefone_1) == normalized_user,
                    _digits_only(Lead.telefone_2) == normalized_user,
                    _digits_only(Lead.telefone_3) == normalized_user,
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    if channel_lower == "telegram":
        result = await session.execute(
            select(Lead)
            .options(selectinload(Lead.lead_base))
            .where(Lead.aux_values["telegram_id"].as_string() == str(user_id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    return None


async def get_latest_interaction_id(
    session: AsyncSession,
    user_id: str,
) -> uuid.UUID | None:
    result = await session.execute(
        select(Interaction.id)
        .where(Interaction.user_id == user_id)
        .order_by(Interaction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def resolve_inbound_status(intent: str, current_status: str) -> str:
    if intent in POSITIVE_INTENTS:
        return "convertido"
    if intent in REFUSAL_INTENTS:
        return "recusou"
    return "em_andamento"


async def track_inbound_lead_interaction(
    session: AsyncSession,
    channel: str,
    user_id: str,
    message: str,
    intent: str,
) -> LeadInteraction | None:
    """Vincula mensagem inbound a LeadInteraction quando o lead é identificado."""
    lead = await find_lead_by_channel_user(session, channel, user_id)
    if lead is None:
        logger.info("Inbound message from untracked contact: channel=%s user_id=%s", channel, user_id)
        return None

    if lead.lead_base is None:
        logger.info("Lead %s found but has no lead_base; skipping tracking", lead.id)
        return None

    campaign_id = lead.lead_base.campaign_id
    channel_lower = channel.lower()
    last_interaction_id = await get_latest_interaction_id(session, user_id)

    existing = await session.execute(
        select(LeadInteraction).where(
            LeadInteraction.lead_id == lead.id,
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel_lower,
        )
    )
    current = existing.scalar_one_or_none()

    devolutiva = message[:500] if message else None
    new_status = resolve_inbound_status(intent, current.status if current else "pendente")

    return await upsert_lead_interaction(
        session,
        lead.id,
        campaign_id,
        channel_lower,
        status=new_status,
        devolutiva=devolutiva,
        last_interaction_id=last_interaction_id,
    )
