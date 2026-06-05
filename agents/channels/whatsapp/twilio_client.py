"""Twilio client helpers for outbound WhatsApp messages."""

from twilio.rest import Client

from agents.channels.phone import to_e164
from app.core.config import settings


def _whatsapp_address(number: str) -> str:
    if number.startswith("whatsapp:"):
        return number
    return f"whatsapp:{number}"


def _normalize_whatsapp_recipient(to: str) -> str:
    """E.164 antes do prefixo whatsapp: (mesma normalização do canal voice)."""
    raw = to.removeprefix("whatsapp:") if to.startswith("whatsapp:") else to
    return to_e164(raw)


def send_whatsapp_message(to: str, body: str) -> str:
    """Send a WhatsApp message via Twilio. Returns the message SID."""
    recipient_e164 = _normalize_whatsapp_recipient(to)
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    message = client.messages.create(
        body=body,
        from_=_whatsapp_address(settings.twilio_phone_number),
        to=_whatsapp_address(recipient_e164),
    )
    return message.sid
