"""Twilio client helpers for outbound WhatsApp messages."""

import json
import logging

import httpx
from twilio.rest import Client

from agents.channels.phone import to_e164
from app.core.config import settings
from app.services.whatsapp_delivery import WHATSAPP_STATUS_CALLBACK_PATH

logger = logging.getLogger(__name__)

_TWILIO_TYPING_INDICATOR_URL = "https://messaging.twilio.com/v2/Indicators/Typing.json"

ContentVariablesInput = dict[str, str] | str


def _normalize_content_variables(variables: ContentVariablesInput) -> dict[str, str]:
    """
    Normaliza variáveis de template para dict.

    Aceita dict ou string JSON já serializada (evita ``json.dumps`` duplo no caller).
    """
    if isinstance(variables, str):
        parsed: object = json.loads(variables.strip())
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        if not isinstance(parsed, dict):
            raise ValueError("content_variables must be a JSON object")
        return {str(key): str(value) for key, value in parsed.items()}
    return {str(key): str(value) for key, value in variables.items()}


def encode_content_variables(variables: ContentVariablesInput) -> str:
    """Serializa variáveis de template para o campo ContentVariables da API Twilio."""
    normalized = _normalize_content_variables(variables)
    payload = json.dumps(normalized)
    json.loads(payload)
    return payload


def _whatsapp_status_callback_url() -> str | None:
    """URL pública para status callback; None se PUBLIC_BASE_URL indisponível."""
    try:
        base = settings.require_public_base_url()
    except ValueError as exc:
        logger.warning(
            "PUBLIC_BASE_URL indisponível; status_callback WhatsApp omitido: %s",
            exc,
        )
        return None
    return f"{base}{WHATSAPP_STATUS_CALLBACK_PATH}"


def _whatsapp_address(number: str) -> str:
    if number.startswith("whatsapp:"):
        return number
    return f"whatsapp:{number}"


def _normalize_whatsapp_recipient(to: str) -> str:
    """E.164 antes do prefixo whatsapp: (mesma normalização do canal voice)."""
    raw = to.removeprefix("whatsapp:") if to.startswith("whatsapp:") else to
    return to_e164(raw)


def send_whatsapp_typing_indicator(message_sid: str) -> bool:
    """
    Send WhatsApp typing indicator (Twilio Public Beta).

    Requires the inbound MessageSid (SM...). Marks the message as read and shows
    typing for up to ~25s or until the outbound reply is delivered.
    """
    sid = (message_sid or "").strip()
    if not sid:
        return False
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return False

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                _TWILIO_TYPING_INDICATOR_URL,
                data={"messageId": sid, "channel": "whatsapp"},
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
            response.raise_for_status()
        return True
    except Exception:
        logger.warning(
            "Falha ao enviar typing indicator WhatsApp message_sid=%s",
            sid,
            exc_info=True,
        )
        return False


def send_whatsapp_message(
    to: str,
    body: str | None = None,
    *,
    content_sid: str | None = None,
    content_variables: ContentVariablesInput | None = None,
) -> str:
    """
    Send a WhatsApp message via Twilio.

    Exatamente um de ``body`` (texto livre) ou ``content_sid`` (template Meta).
    Returns the message SID (criação aceita, não entrega).
    """
    has_body = bool((body or "").strip())
    has_template = bool((content_sid or "").strip())
    if content_variables is not None and not has_template:
        raise ValueError("content_variables requires content_sid")
    if has_body == has_template:
        raise ValueError(
            "send_whatsapp_message requires exactly one of body or content_sid"
        )

    recipient_e164 = _normalize_whatsapp_recipient(to)
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    create_kwargs: dict = {
        "from_": _whatsapp_address(settings.twilio_phone_number),
        "to": _whatsapp_address(recipient_e164),
    }
    if has_body:
        create_kwargs["body"] = body
    else:
        create_kwargs["content_sid"] = content_sid
        if content_variables is not None:
            create_kwargs["content_variables"] = encode_content_variables(
                content_variables
            )

    callback_url = _whatsapp_status_callback_url()
    if callback_url:
        create_kwargs["status_callback"] = callback_url

    message = client.messages.create(**create_kwargs)
    initial_status = (getattr(message, "status", None) or "queued").strip().lower()
    logger.info(
        "WhatsApp message CREATED sid=%s to=%s status=%s mode=%s (delivery pending callback)",
        message.sid,
        recipient_e164,
        initial_status,
        "template" if has_template else "freeform",
    )
    return message.sid
