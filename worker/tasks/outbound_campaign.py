"""Outbound campaign tasks — modo ATIVO."""

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.channels.phone import to_e164
from agents.channels.telegram.client import send_telegram_message, send_telegram_video
from agents.channels.voice.twilio_voice_client import (
    MAX_TWIML_QUERY_TEXT_CHARS,
    build_outbound_audio_twiml_url,
    build_outbound_twiml_url,
    make_outbound_call,
)
from agents.channels.whatsapp.twilio_client import send_whatsapp_message
from agents.orchestrator.router import route_message
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.avatar_video import gerar_video_avatar
from app.services.voice_audio import gerar_audio_chamada
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.core.activation_cadence_text import FOLLOWUP_TRIGGER_MESSAGE
from app.core.activation_defaults import channel_family, normalize_channel_type
from app.services.activation_slots import release_slot
from app.services.capacity_service import release_outbound_capacity_for_lead
from worker.celery_app import celery
from worker.tasks.conversation_routing import agent_personality_context, agent_routing_metadata
from worker.tasks.lead_tracking import upsert_lead_interaction

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
    if channel in ("telegram", "video"):
        telegram_id = lead.aux_values.get("telegram_id")
        return str(telegram_id) if telegram_id else None
    if channel in ("whatsapp", "voice"):
        return get_phone(lead)
    return None


def _agent_context_for_campaign(agent: Agent, *, followup: bool = False) -> dict:
    ctx = agent_routing_metadata(agent)
    personality = agent_personality_context(agent)
    if followup:
        personality = f"{personality}\n\n{FOLLOWUP_TRIGGER_MESSAGE}"
    ctx["agent_personality"] = personality
    return ctx


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
    response: str,
    *,
    first_touch: bool = True,
) -> bool:
    """Envia texto/mídia no canal. Retorna True se entrega ok."""
    if channel == "whatsapp":
        send_whatsapp_message(recipient, response)
        return True
    if channel == "telegram":
        await send_telegram_message(recipient, response)
        return True
    if channel == "video":
        speech_text = (response or "").strip()
        if not speech_text:
            speech_text = "Desculpe, não consegui gerar a mensagem de vídeo no momento."
        caption = speech_text[:1024]
        try:
            filename = await gerar_video_avatar(speech_text)
            video_path = f"{settings.avatar_video_root.rstrip('/')}/{filename}"
            await send_telegram_video(recipient, video_path, caption=caption)
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="acionado",
                devolutiva=f"telegram_video={filename}",
                set_acionamento=first_touch,
                record_outbound_attempt=True,
            )
            logger.info(
                "Video outbound sent via Telegram for lead %s (file=%s, chat=%s)",
                lead.id,
                filename,
                recipient,
            )
            return True
        except Exception as exc:
            logger.exception(
                "Video outbound failed for lead %s (telegram_id=%s): %s",
                lead.id,
                recipient,
                exc,
            )
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="erro",
                devolutiva=str(exc),
            )
            return False
    if channel == "voice":
        speech_text = (response or "").strip()
        if not speech_text:
            speech_text = "Desculpe, não consegui gerar a mensagem de voz no momento."
        speech_text_for_say = speech_text
        if len(speech_text_for_say) > MAX_TWIML_QUERY_TEXT_CHARS:
            logger.info(
                "Truncating voice speech for Say fallback (lead %s) to %s chars",
                lead.id,
                MAX_TWIML_QUERY_TEXT_CHARS,
            )
            speech_text_for_say = speech_text_for_say[:MAX_TWIML_QUERY_TEXT_CHARS]
        try:
            recipient_e164 = to_e164(recipient)
            try:
                filename = await gerar_audio_chamada(speech_text)
                twiml_url = build_outbound_audio_twiml_url(filename)
                logger.info(
                    "Voice outbound using Coqui MP3 for lead %s (file=%s)",
                    lead.id,
                    filename,
                )
            except Exception as audio_exc:
                logger.warning(
                    "Coqui/ffmpeg indisponível para lead %s, fallback <Say>: %s",
                    lead.id,
                    audio_exc,
                )
                twiml_url = build_outbound_twiml_url(speech_text_for_say)
            call_sid = make_outbound_call(recipient_e164, twiml_url)
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="acionado",
                devolutiva=f"twilio_call_sid={call_sid}",
                set_acionamento=first_touch,
                record_outbound_attempt=True,
            )
            logger.info(
                "Voice outbound call placed for lead %s to %s (sid=%s)",
                lead.id,
                recipient_e164,
                call_sid,
            )
            return True
        except Exception as exc:
            logger.exception(
                "Voice outbound failed for lead %s (user_id=%s): %s",
                lead.id,
                recipient,
                exc,
            )
            await upsert_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
                status="erro",
                devolutiva=str(exc),
            )
            return False
    logger.warning("Unsupported channel %s for lead %s", channel, lead.id)
    return False


async def _send_on_channel(
    session: AsyncSession,
    lead: Lead,
    campaign: Campaign,
    channel_type: str,
    *,
    followup: bool = False,
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

    agent = campaign.agent
    if agent is None:
        raise ValueError(f"Campaign {campaign.id} has no agent")

    prompt = FOLLOWUP_TRIGGER_MESSAGE if followup else _build_initial_message(lead, campaign)
    agent_context = _agent_context_for_campaign(agent, followup=followup)
    result = await route_message(
        prompt,
        channel,
        recipient,
        agent_context=agent_context,
    )
    response = result.get("response", "")

    if channel in ("whatsapp", "telegram"):
        if not (response or "").strip():
            logger.warning("Empty response for lead %s channel %s", lead.id, channel)
            return None
        try:
            await _deliver_message(session, lead, campaign, channel, recipient, response)
        except Exception as exc:
            logger.exception(
                "Messaging outbound failed lead=%s channel=%s: %s",
                lead.id,
                channel,
                exc,
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
        await upsert_lead_interaction(
            session,
            lead.id,
            campaign.id,
            channel,
            status="acionado",
            set_acionamento=not followup,
            record_outbound_attempt=True,
            devolutiva=(response or "")[:500] if followup else None,
        )
    else:
        ok = await _deliver_message(
            session,
            lead,
            campaign,
            channel,
            recipient,
            response,
            first_touch=not followup,
        )
        if not ok:
            return None

    return {"channel": channel, "recipient": recipient, "response": response, "followup": followup}


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
    if family == "voice_video":
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
) -> dict:
    """Envia mensagem ativa (1ª abordagem) para um lead no canal indicado."""
    try:
        return asyncio.run(
            _send_campaign_message(
                lead_id,
                campaign_id,
                channel_type,
                slot_token=slot_token,
                agent_id=agent_id,
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
        return asyncio.run(
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
