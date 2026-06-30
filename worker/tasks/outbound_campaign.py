"""Outbound campaign tasks — modo ATIVO."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.orchestrator.router import route_message
from app.core.config import WhatsAppTemplatePurpose
from app.core.database import AsyncSessionLocal
from app.models.lead_interaction import LeadInteraction
from app.services.whatsapp_outbound import (
    WhatsAppSendMode,
    build_content_variables,
    resolve_whatsapp_send_mode,
)
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.core.activation_cadence_text import FOLLOWUP_TRIGGER_MESSAGE
from app.core.activation_defaults import channel_family, normalize_channel_type
from app.services.activation_slots import release_slot
from app.services.capacity_service import release_outbound_capacity_for_lead
from worker.async_runner import run_celery_async
from worker.celery_app import celery
from app.services.agent_context import enrich_agent_context_with_identity
from worker.tasks.conversation_routing import agent_personality_context, agent_routing_metadata
from worker.tasks.lead_tracking import upsert_lead_interaction

from app.services.outbound_delivery import DeliverResult, deliver_outbound_message

logger = logging.getLogger(__name__)


def get_phone(lead: Lead) -> str | None:
    """Retorna o primeiro telefone não-nulo entre telefone_1, telefone_2 e telefone_3."""
    for phone in (lead.telefone_1, lead.telefone_2, lead.telefone_3):
        if phone and phone.strip():
            return phone.strip()
    return None


def _build_initial_message(lead: Lead, campaign: Campaign) -> str:
    aux1 = lead.aux_values.get("aux1", "")
    aux_suffix = f" {aux1}" if aux1 else ""
    return lead.aux_values.get(
        "initial_message",
        (
            f"Olá {lead.nome_cliente}{aux_suffix}, tudo bem? "
            f"Sou o assistente virtual da {campaign.name}."
        ),
    )


def _resolve_recipient(lead: Lead, channel_type: str) -> str | None:
    channel = channel_type.lower()
    if channel == "telegram":
        telegram_id = lead.aux_values.get("telegram_id")
        return str(telegram_id) if telegram_id else None
    if channel in ("whatsapp", "voice"):
        return get_phone(lead)
    return None


async def _agent_context_for_campaign(
    session: AsyncSession,
    agent: Agent,
    campaign: Campaign,
    *,
    lead: Lead | None = None,
    followup: bool = False,
) -> dict:
    ctx = agent_routing_metadata(agent)
    ctx["owner_user_id"] = str(campaign.user_id)
    personality = agent_personality_context(agent)
    if followup:
        personality = f"{personality}\n\n{FOLLOWUP_TRIGGER_MESSAGE}"
    ctx["agent_personality"] = personality
    return await enrich_agent_context_with_identity(
        session,
        ctx,
        agent,
        lead=lead,
        campaign=campaign,
    )


async def _fetch_lead_interaction(
    session: AsyncSession,
    lead_id: uuid.UUID,
    campaign_id: uuid.UUID,
    channel_type: str,
) -> LeadInteraction | None:
    """LeadInteraction atual para (lead, campanha, canal), se existir."""
    channel = channel_type.lower()
    result = await session.execute(
        select(LeadInteraction)
        .where(
            LeadInteraction.lead_id == lead_id,
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _block_non_active_outbound(
    session: AsyncSession,
    lead: Lead,
    campaign: Campaign,
    channel_type: str,
) -> None:
    """Registra bloqueio quando a campanha não usa agente ACTIVE."""
    channel = channel_type.lower()
    warning = (
        f"Campanha {campaign.id} usa agente não-ACTIVE; disparo outbound bloqueado"
    )
    logger.warning("%s (lead=%s channel=%s)", warning, lead.id, channel)
    await upsert_lead_interaction(
        session,
        lead.id,
        campaign.id,
        channel,
        status="erro",
        devolutiva=warning,
    )


async def _deliver_message(
    session: AsyncSession,
    lead: Lead,
    campaign: Campaign,
    channel: str,
    recipient: str,
    response: str | None = None,
    *,
    first_touch: bool = True,
    content_sid: str | None = None,
    content_variables: dict[str, str] | None = None,
) -> DeliverResult:
    """Envia via ``deliver_outbound_message`` e registra LeadInteraction em voz."""
    delivery = await deliver_outbound_message(
        channel,
        recipient,
        response or "",
        lead=lead,
        content_sid=content_sid,
        content_variables=content_variables,
    )
    if channel == "voice":
        if delivery.ok and delivery.twilio_call_sid:
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="acionado",
                devolutiva=f"twilio_call_sid={delivery.twilio_call_sid}",
                set_acionamento=first_touch,
                record_outbound_attempt=True,
                twilio_call_sid=delivery.twilio_call_sid,
            )
        elif not delivery.ok:
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="erro",
                devolutiva=delivery.error or "voice delivery failed",
            )
    return delivery


async def _send_on_channel(
    session: AsyncSession,
    lead: Lead,
    campaign: Campaign,
    channel_type: str,
    *,
    followup: bool = False,
    agent_override: Agent | None = None,
    force_whatsapp_template: bool = False,
    message_override: str | None = None,
) -> dict | None:
    channel = channel_type.lower()
    recipient = _resolve_recipient(lead, channel)

    if not recipient:
        logger.warning(
            "Skipping lead %s on channel %s: no recipient available",
            lead.id,
            channel,
        )
        await upsert_lead_interaction(
            session,
            lead.id,
            campaign.id,
            channel,
            status="erro",
            devolutiva=f"Sem destinatário disponível para o canal {channel}",
        )
        return None

    agent = agent_override if agent_override is not None else campaign.agent
    if agent is None:
        raise ValueError(f"Campaign {campaign.id} has no agent")

    purpose: WhatsAppTemplatePurpose = "followup" if followup else "inicial"
    record = await _fetch_lead_interaction(session, lead.id, campaign.id, channel)

    whatsapp_send_mode: WhatsAppSendMode | None = None
    if channel == "whatsapp":
        whatsapp_send_mode = resolve_whatsapp_send_mode(
            purpose,
            record,
            lead=lead,
            ignore_service_window=force_whatsapp_template,
        )

    use_whatsapp_template = (
        channel == "whatsapp"
        and whatsapp_send_mode is not None
        and whatsapp_send_mode.mode == "template"
        and message_override is None
    )

    response = ""
    if message_override is not None:
        response = message_override.strip()
        if not response:
            logger.warning("Empty message_override for lead %s channel %s", lead.id, channel)
            return None
    elif use_whatsapp_template:
        logger.info(
            "WhatsApp outbound template purpose=%s lead=%s sid=%s (LLM skipped)",
            purpose,
            lead.id,
            whatsapp_send_mode.content_sid,
        )
    else:
        prompt = FOLLOWUP_TRIGGER_MESSAGE if followup else _build_initial_message(lead, campaign)
        agent_context = await _agent_context_for_campaign(
            session,
            agent,
            campaign,
            lead=lead,
            followup=followup,
        )
        result = await route_message(
            prompt,
            channel,
            recipient,
            agent_context=agent_context,
        )
        response = result.get("response", "")

    if channel in ("whatsapp", "telegram"):
        if not use_whatsapp_template and not (response or "").strip():
            logger.warning("Empty response for lead %s channel %s", lead.id, channel)
            return None
        try:
            delivery = await _deliver_message(
                session,
                lead,
                campaign,
                channel,
                recipient,
                response if not use_whatsapp_template else None,
                content_sid=whatsapp_send_mode.content_sid if use_whatsapp_template else None,
                content_variables=(
                    whatsapp_send_mode.content_variables or build_content_variables(lead)
                    if use_whatsapp_template
                    else None
                ),
            )
        except Exception as exc:
            logger.error(
                "Outbound delivery failed: channel=%s lead_id=%s recipient=%s error=%s",
                channel,
                lead.id,
                recipient,
                exc,
                exc_info=True,
            )
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="erro",
                devolutiva=str(exc),
            )
            return None
        followup_devolutiva: str | None = None
        if followup:
            followup_devolutiva = (
                (response or "")[:500]
                if response
                else f"template:{purpose}"
            )
        await upsert_lead_interaction(
            session,
            lead.id,
            campaign.id,
            channel,
            status="acionado",
            set_acionamento=not followup,
            record_outbound_attempt=True,
            devolutiva=followup_devolutiva,
            twilio_message_sid=delivery.twilio_message_sid,
            last_delivery_status=delivery.initial_delivery_status,
        )
    else:
        delivery = await _deliver_message(
            session,
            lead,
            campaign,
            channel,
            recipient,
            response,
            first_touch=not followup,
        )
        if not delivery.ok:
            return None

    return {
        "channel": channel,
        "recipient": recipient,
        "response": response or None,
        "followup": followup,
        "whatsapp_template": use_whatsapp_template,
        "content_sid": whatsapp_send_mode.content_sid if use_whatsapp_template else None,
    }


async def _send_test_dispatch(
    session: AsyncSession,
    lead: Lead,
    campaign: Campaign,
    channel_type: str,
    agent: Agent,
) -> dict:
    """
    Disparo ad-hoc síncrono: um canal, agente explícito, sem cadência/scheduler.

    Com templates WhatsApp ON, ignora a janela de 24h e envia template inicial
    (mesmo ``send_whatsapp_message`` + ``encode_content_variables`` do acionamento real).
    """
    channel = normalize_channel_type(channel_type)
    result = await _send_on_channel(
        session,
        lead,
        campaign,
        channel,
        followup=False,
        agent_override=agent,
        force_whatsapp_template=True,
    )
    if result is None:
        return {
            "channel": channel,
            "recipient": _resolve_recipient(lead, channel),
            "response": None,
            "error": "Falha no disparo (sem destinatário, resposta vazia ou erro de entrega)",
        }
    return {
        "channel": result["channel"],
        "recipient": result["recipient"],
        "response": result.get("response"),
        "error": None,
    }


def _release_slot_after_dispatch(
    agent_id: str | None,
    channel_type: str | None,
    slot_token: str | None,
    *,
    delivery_ok: bool,
    lead_id: str | None = None,
) -> None:
    """Libera slot + peso global outbound (R-C) conforme Camada D."""
    if not channel_type:
        return
    channel = normalize_channel_type(channel_type)
    family = channel_family(channel)
    if not delivery_ok and lead_id:
        release_outbound_capacity_for_lead(lead_id, channel)
        return
    if not slot_token or not agent_id:
        return
    if family == "voice":
        if not delivery_ok:
            release_slot(agent_id, channel, slot_token)
        return
    if not delivery_ok:
        release_slot(agent_id, channel, slot_token)


async def _send_campaign_message(
    lead_id: str,
    campaign_id: str,
    channel_type: str | None = None,
    *,
    followup: bool = False,
    slot_token: str | None = None,
    agent_id: str | None = None,
    message_override: str | None = None,
) -> dict:
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()

    async with AsyncSessionLocal() as session:
        lead_result = await session.execute(
            select(Lead)
            .options(selectinload(Lead.lead_base).selectinload(LeadBase.lead_base_channels))
            .where(Lead.id == uuid.UUID(lead_id))
        )
        lead = lead_result.scalar_one_or_none()
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        campaign_result = await session.execute(
            select(Campaign)
            .options(selectinload(Campaign.agent))
            .where(Campaign.id == uuid.UUID(campaign_id))
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign.agent is None:
            raise ValueError(f"Campaign {campaign_id} has no agent")

        if campaign.agent.mode != AgentMode.ACTIVE:
            # Gate de prospecção: campanhas outbound exigem agente ACTIVE.
            # Lembretes de agendamento usam worker.tasks.appointment_reminder (isentos).
            if lead.lead_base is None or not lead.lead_base.lead_base_channels:
                logger.warning(
                    "Lead %s has no lead_base_channels; non-ACTIVE outbound block only logged",
                    lead.id,
                )
                return {
                    "lead_id": lead_id,
                    "campaign_id": campaign_id,
                    "channels": [],
                    "blocked": True,
                    "reason": "campaign_agent_not_active",
                }
            for base_channel in lead.lead_base.lead_base_channels:
                await _block_non_active_outbound(
                    session,
                    lead,
                    campaign,
                    base_channel.channel_type,
                )
            await session.commit()
            return {
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "channels": [],
                "blocked": True,
                "reason": "campaign_agent_not_active",
            }

        if lead.lead_base is None or not lead.lead_base.lead_base_channels:
            logger.warning("Lead %s has no lead_base_channels configured", lead.id)
            return {"lead_id": lead_id, "campaign_id": campaign_id, "channels": []}

        filter_channel = channel_type.lower().strip() if channel_type else None
        channel_results: list[dict] = []
        delivery_ok = False
        for base_channel in lead.lead_base.lead_base_channels:
            if filter_channel is not None and base_channel.channel_type.lower() != filter_channel:
                continue
            result = await _send_on_channel(
                session,
                lead,
                campaign,
                base_channel.channel_type,
                followup=followup,
                message_override=message_override,
            )
            if result is not None:
                channel_results.append(result)
                delivery_ok = True

        await session.commit()

        _release_slot_after_dispatch(
            agent_id,
            channel_type,
            slot_token,
            delivery_ok=delivery_ok,
            lead_id=lead_id,
        )

        return {
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "channels": channel_results,
            "followup": followup,
        }


@celery.task(bind=True, max_retries=3)
def send_campaign_message(
    self,
    lead_id: str,
    campaign_id: str,
    channel_type: str | None = None,
    slot_token: str | None = None,
    agent_id: str | None = None,
    message_override: str | None = None,
) -> dict:
    """Envia mensagem ativa (1ª abordagem) para um lead no canal indicado."""
    try:
        return run_celery_async(
            _send_campaign_message(
                lead_id,
                campaign_id,
                channel_type,
                slot_token=slot_token,
                agent_id=agent_id,
                message_override=message_override,
            )
        )
    except Exception as exc:
        _release_slot_after_dispatch(
            agent_id, channel_type, slot_token, delivery_ok=False, lead_id=lead_id
        )
        raise self.retry(exc=exc, countdown=60) from exc


@celery.task(bind=True, max_retries=3)
def send_campaign_followup(
    self,
    lead_id: str,
    campaign_id: str,
    channel_type: str,
    slot_token: str | None = None,
    agent_id: str | None = None,
) -> dict:
    """Envia follow-up (2ª mensagem) quando o lead não respondeu."""
    try:
        return run_celery_async(
            _send_campaign_message(
                lead_id,
                campaign_id,
                channel_type,
                followup=True,
                slot_token=slot_token,
                agent_id=agent_id,
            )
        )
    except Exception as exc:
        _release_slot_after_dispatch(
            agent_id, channel_type, slot_token, delivery_ok=False, lead_id=lead_id
        )
        raise self.retry(exc=exc, countdown=60) from exc
