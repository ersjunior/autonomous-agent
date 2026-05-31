"""WhatsApp webhook handler wired to the LangGraph orchestrator."""

import xml.sax.saxutils

from agents.orchestrator.router import route_message


class WhatsAppHandler:
    async def handle_webhook(self, payload: dict) -> str:
        body = payload.get("Body", "")
        from_number = payload.get("From", "")

        if not body or not from_number:
            return "<Response></Response>"

        result = await route_message(body, "whatsapp", from_number)
        response_text = result.get("response", "")
        escaped = xml.sax.saxutils.escape(response_text)
        return f"<Response><Message>{escaped}</Message></Response>"
