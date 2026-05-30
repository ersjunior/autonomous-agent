"""Twilio client helpers for outbound WhatsApp messages."""

from twilio.rest import Client

from app.core.config import settings


def _whatsapp_address(number: str) -> str:
    if number.startswith("whatsapp:"):
        return number
    return f"whatsapp:{number}"


def send_whatsapp_message(to: str, body: str) -> str:
    """Send a WhatsApp message via Twilio. Returns the message SID."""
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    message = client.messages.create(
        body=body,
        from_=_whatsapp_address(settings.twilio_phone_number),
        to=_whatsapp_address(to),
    )
    return message.sid
