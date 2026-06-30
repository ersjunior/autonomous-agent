"""Entrega outbound por canal — sem gate de modo de campanha.

Usado por campanhas (via ``_deliver_message``) e por lembretes de agendamento
(caminho direto isento do bloqueio RECEPTIVE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.channels.phone import to_e164
from agents.channels.telegram.client import send_telegram_message
from agents.channels.voice.twilio_voice_client import (
    MAX_TWIML_QUERY_TEXT_CHARS,
    build_outbound_audio_twiml_url,
    build_outbound_twiml_url,
    make_outbound_call,
)
from agents.channels.whatsapp.twilio_client import send_whatsapp_message
from app.models.lead import Lead
from app.services.voice_audio import gerar_audio_chamada
from app.services.whatsapp_outbound import build_content_variables

logger = logging.getLogger(__name__)


@dataclass
class DeliverResult:
    ok: bool
    twilio_message_sid: str | None = None
    initial_delivery_status: str | None = None
    twilio_call_sid: str | None = None
    error: str | None = None


async def deliver_outbound_message(
    channel: str,
    recipient: str,
    text: str,
    *,
    lead: Lead | None = None,
    content_sid: str | None = None,
    content_variables: dict[str, str] | None = None,
) -> DeliverResult:
    """
    Envia mensagem no canal (whatsapp / telegram / voice).

    Não verifica modo do agente nem campanha — apenas transporte.
    """
    ch = channel.lower()

    if ch == "whatsapp":
        try:
            if content_sid:
                variables = content_variables or (
                    build_content_variables(lead) if lead is not None else {}
                )
                message_sid = send_whatsapp_message(
                    recipient,
                    content_sid=content_sid,
                    content_variables=variables,
                )
            else:
                message_sid = send_whatsapp_message(recipient, text)
            return DeliverResult(
                ok=True,
                twilio_message_sid=message_sid,
                initial_delivery_status="queued",
            )
        except Exception as exc:
            logger.exception(
                "WhatsApp delivery failed recipient=%s error=%s",
                recipient,
                exc,
            )
            return DeliverResult(ok=False, error=str(exc))

    if ch == "telegram":
        try:
            await send_telegram_message(recipient, text)
            return DeliverResult(ok=True)
        except Exception as exc:
            logger.exception(
                "Telegram delivery failed recipient=%s error=%s",
                recipient,
                exc,
            )
            return DeliverResult(ok=False, error=str(exc))

    if ch == "voice":
        speech_text = (text or "").strip()
        if not speech_text:
            speech_text = "Desculpe, não consegui gerar a mensagem de voz no momento."
        speech_text_for_say = speech_text
        if len(speech_text_for_say) > MAX_TWIML_QUERY_TEXT_CHARS:
            lead_id = lead.id if lead is not None else "?"
            logger.info(
                "Truncating voice speech for Say fallback (lead %s) to %s chars",
                lead_id,
                MAX_TWIML_QUERY_TEXT_CHARS,
            )
            speech_text_for_say = speech_text_for_say[:MAX_TWIML_QUERY_TEXT_CHARS]
        try:
            recipient_e164 = to_e164(recipient)
            try:
                filename = await gerar_audio_chamada(speech_text)
                twiml_url = build_outbound_audio_twiml_url(filename)
                if lead is not None:
                    logger.info(
                        "Voice outbound using Coqui MP3 for lead %s (file=%s)",
                        lead.id,
                        filename,
                    )
            except Exception as audio_exc:
                if lead is not None:
                    logger.warning(
                        "Coqui/ffmpeg indisponível para lead %s, fallback <Say>: %s",
                        lead.id,
                        audio_exc,
                    )
                twiml_url = build_outbound_twiml_url(speech_text_for_say)
            call_sid = make_outbound_call(recipient_e164, twiml_url)
            from app.services.voice_call_state import remember_call_from_number

            remember_call_from_number(call_sid, recipient_e164)
            if lead is not None:
                logger.info(
                    "Voice outbound call placed for lead %s to %s (sid=%s)",
                    lead.id,
                    recipient_e164,
                    call_sid,
                )
            return DeliverResult(ok=True, twilio_call_sid=call_sid)
        except Exception as exc:
            if lead is not None:
                logger.exception(
                    "Voice outbound failed for lead %s (to=%s): %s",
                    lead.id,
                    recipient,
                    exc,
                )
            return DeliverResult(ok=False, error=str(exc))

    logger.warning("Unsupported channel %s for outbound delivery", ch)
    return DeliverResult(ok=False, error=f"unsupported_channel:{ch}")
