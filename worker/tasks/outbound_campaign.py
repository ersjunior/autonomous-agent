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
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from worker.celery_app import celery
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
        # Canal VIDEO (MVP): entrega o MP4 via Telegram — destinatário = telegram_id
        telegram_id = lead.aux_values.get("telegram_id")
        return str(telegram_id) if telegram_id else None
    if channel in ("whatsapp", "voice"):
        return get_phone(lead)
    return None


async def _send_on_channel(
    session: AsyncSession,
    lead: Lead,
    campaign: Campaign,
    channel_type: str,
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

    await upsert_lead_interaction(
        session,
        lead.id,
        campaign.id,
        channel,
        status="acionado",
        set_acionamento=True,
    )

    initial_message = _build_initial_message(lead, campaign)
    result = await route_message(initial_message, channel, recipient)
    response = result.get("response", "")

    if channel == "whatsapp":
        send_whatsapp_message(recipient, response)
    elif channel == "telegram":
        await send_telegram_message(recipient, response)
    elif channel == "video":
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
            )
            logger.info(
                "Video outbound sent via Telegram for lead %s (file=%s, chat=%s)",
                lead.id,
                filename,
                recipient,
            )
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
            return None
    elif channel == "voice":
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
            )
            logger.info(
                "Voice outbound call placed for lead %s to %s (sid=%s)",
                lead.id,
                recipient_e164,
                call_sid,
            )
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
            return None
    else:
        logger.warning("Unsupported channel %s for lead %s", channel, lead.id)
        return None

    return {"channel": channel, "recipient": recipient, "response": response}


async def _send_campaign_message(lead_id: str, campaign_id: str) -> dict:
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
            select(Campaign).where(Campaign.id == uuid.UUID(campaign_id))
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        if lead.lead_base is None or not lead.lead_base.lead_base_channels:
            logger.warning("Lead %s has no lead_base_channels configured", lead.id)
            return {"lead_id": lead_id, "campaign_id": campaign_id, "channels": []}

        channel_results: list[dict] = []
        for base_channel in lead.lead_base.lead_base_channels:
            result = await _send_on_channel(session, lead, campaign, base_channel.channel_type)
            if result is not None:
                channel_results.append(result)

        await session.commit()

        return {
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "channels": channel_results,
        }


@celery.task(bind=True, max_retries=3)
def send_campaign_message(self, lead_id: str, campaign_id: str) -> dict:
    """Envia mensagem ativa para um lead nos canais configurados na base."""
    from app.services.settings_sync import ensure_settings_fresh_sync

    ensure_settings_fresh_sync()
    try:
        return asyncio.run(_send_campaign_message(lead_id, campaign_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc
