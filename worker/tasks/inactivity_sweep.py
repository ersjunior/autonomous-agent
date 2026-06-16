"""
Sweep de inatividade — mensageria WhatsApp/Telegram (em_andamento).

Aviso fixo após INACTIVITY_WARNING_MINUTES sem resposta do cliente; encerra após
INACTIVITY_CLOSE_MINUTES adicionais com tabulação por modo (ACTIVE→NEG:ABANDONO,
RECEPTIVE→NEG:AUSENTE). Só lifecycle_version >= 1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from agents.channels.telegram.client import send_telegram_message
from agents.channels.whatsapp.twilio_client import send_whatsapp_message
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.inactivity_text import INACTIVITY_WARNING_MESSAGE
from app.models.agent import AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.services.activation_cadence import client_is_silent, client_silent_since_warning
from app.services.activation_slots import release_slot_for_lead
from app.services.capacity_service import (
    release_outbound_capacity_for_lead,
    release_receptive_capacity_for_lead,
)
from app.services.human_handoff import is_in_human_mode
from app.services.tabulacao_assignment import apply_tabulacao
from app.services.whatsapp_outbound import build_content_variables, resolve_whatsapp_send_mode
from worker.async_runner import run_celery_async
from worker.celery_app import celery
from worker.tasks.outbound_campaign import _resolve_recipient

logger = logging.getLogger(__name__)

_MESSAGING_CHANNELS = ("whatsapp", "telegram")


def _client_silent_sql_filter():
    """Agente falou por último: sem inbound após último outbound/acionamento."""
    last_outbound = LeadInteraction.data_ultima_tentativa
    return or_(
        LeadInteraction.data_ultimo_contato.is_(None),
        LeadInteraction.data_ultimo_contato <= last_outbound,
        and_(
            LeadInteraction.data_ultima_tentativa.is_(None),
            LeadInteraction.data_ultimo_contato <= LeadInteraction.data_acionamento,
        ),
    )


def _base_candidate_filter():
    return and_(
        LeadInteraction.status == "em_andamento",
        LeadInteraction.channel_type.in_(_MESSAGING_CHANNELS),
        LeadInteraction.lifecycle_version >= 1,
        or_(
            LeadInteraction.data_ultima_tentativa.isnot(None),
            LeadInteraction.data_acionamento.isnot(None),
        ),
    )


async def _send_inactivity_warning(
    channel: str,
    recipient: str,
    text: str,
    *,
    record: LeadInteraction,
    lead: Lead | None,
) -> str | None:
    """
    Envia aviso de inatividade. Retorna Twilio message SID no WhatsApp; None no Telegram.

    WhatsApp fora da janela 24h + templates ON → template ``retomada`` (evita 63016).
    """
    ch = channel.lower()
    try:
        if ch == "whatsapp":
            mode = resolve_whatsapp_send_mode("retomada", record, lead=lead)
            if mode.mode == "template":
                variables = mode.content_variables
                if variables is None and lead is not None:
                    variables = build_content_variables(lead)
                return send_whatsapp_message(
                    recipient,
                    content_sid=mode.content_sid,
                    content_variables=variables,
                )
            return send_whatsapp_message(recipient, text)
        if ch == "telegram":
            await send_telegram_message(recipient, text)
            return None
    except Exception:
        logger.exception(
            "Falha ao enviar aviso de inatividade channel=%s recipient=%s",
            channel,
            recipient,
        )
    return None


async def _close_inactive_interaction(
    session,
    record: LeadInteraction,
    *,
    agent_mode: AgentMode,
) -> None:
    record.status = "nao_atendido"
    codigo = "NEG:ABANDONO" if agent_mode == AgentMode.ACTIVE else "NEG:AUSENTE"
    await apply_tabulacao(
        session,
        record,
        status_interno="nao_atendido",
        channel=record.channel_type,
        tabulacao_codigo=codigo,
        origem="INACTIVITY_SWEEP",
    )
    release_slot_for_lead(str(record.lead_id), record.channel_type)
    release_receptive_capacity_for_lead(str(record.lead_id), record.channel_type)
    release_outbound_capacity_for_lead(str(record.lead_id), record.channel_type)


async def _sweep_inactivity_with_session(session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    warning_cutoff = now - timedelta(minutes=settings.inactivity_warning_minutes)
    close_cutoff = now - timedelta(minutes=settings.inactivity_close_minutes)

    stats = {"warnings_sent": 0, "closed": 0, "skipped_human_mode": 0}

    warning_result = await session.execute(
        select(LeadInteraction)
        .options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign).selectinload(Campaign.agent),
        )
        .where(
            _base_candidate_filter(),
            LeadInteraction.inactivity_warning_sent_at.is_(None),
            _client_silent_sql_filter(),
            or_(
                and_(
                    LeadInteraction.data_ultima_tentativa.isnot(None),
                    LeadInteraction.data_ultima_tentativa <= warning_cutoff,
                ),
                and_(
                    LeadInteraction.data_ultima_tentativa.is_(None),
                    LeadInteraction.data_acionamento.isnot(None),
                    LeadInteraction.data_acionamento <= warning_cutoff,
                ),
            ),
        )
    )
    warning_candidates = list(warning_result.scalars().all())

    for record in warning_candidates:
        if not client_is_silent(record):
            continue
        agent = record.campaign.agent if record.campaign else None
        if agent is None:
            continue
        recipient = _resolve_recipient(record.lead, record.channel_type)
        if not recipient:
            logger.warning(
                "Inactivity sweep: sem destinatário lead=%s channel=%s",
                record.lead_id,
                record.channel_type,
            )
            continue
        if is_in_human_mode(record.channel_type, recipient):
            stats["skipped_human_mode"] += 1
            continue
        message_sid = await _send_inactivity_warning(
            record.channel_type,
            recipient,
            INACTIVITY_WARNING_MESSAGE,
            record=record,
            lead=record.lead,
        )
        if message_sid is None and record.channel_type.lower() == "whatsapp":
            continue
        if record.channel_type.lower() == "whatsapp" and message_sid:
            record.twilio_message_sid = message_sid
            record.last_delivery_status = "queued"
        record.inactivity_warning_sent_at = now
        record.data_ultima_tentativa = now
        stats["warnings_sent"] += 1

    close_result = await session.execute(
        select(LeadInteraction)
        .options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign).selectinload(Campaign.agent),
        )
        .where(
            _base_candidate_filter(),
            LeadInteraction.inactivity_warning_sent_at.isnot(None),
            LeadInteraction.inactivity_warning_sent_at <= close_cutoff,
            or_(
                LeadInteraction.data_ultimo_contato.is_(None),
                LeadInteraction.data_ultimo_contato
                <= LeadInteraction.inactivity_warning_sent_at,
            ),
        )
    )
    close_candidates = list(close_result.scalars().all())

    for record in close_candidates:
        if not client_silent_since_warning(record):
            continue
        agent = record.campaign.agent if record.campaign else None
        if agent is None:
            continue
        recipient = _resolve_recipient(record.lead, record.channel_type)
        if recipient and is_in_human_mode(record.channel_type, recipient):
            stats["skipped_human_mode"] += 1
            continue
        await _close_inactive_interaction(session, record, agent_mode=agent.mode)
        stats["closed"] += 1

    if stats["warnings_sent"] or stats["closed"]:
        await session.commit()

    logger.info(
        "Inactivity sweep: warnings=%s closed=%s skipped_human=%s "
        "(warning_min=%s close_min=%s)",
        stats["warnings_sent"],
        stats["closed"],
        stats["skipped_human_mode"],
        settings.inactivity_warning_minutes,
        settings.inactivity_close_minutes,
    )
    return stats


async def _sweep_inactivity_async() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        return await _sweep_inactivity_with_session(session)


@celery.task(name="worker.tasks.inactivity_sweep.sweep_messaging_inactivity")
def sweep_messaging_inactivity() -> dict[str, int]:
    """Beat: aviso e encerramento por inatividade em mensageria (lifecycle_version >= 1)."""
    return run_celery_async(_sweep_inactivity_async())
