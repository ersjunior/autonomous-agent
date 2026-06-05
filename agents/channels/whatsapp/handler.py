"""WhatsApp webhook handler — enfileira inbound no Celery (R-A.0).

O webhook responde TwiML vazio imediatamente; o worker envia a resposta via
``send_whatsapp_message`` (API Twilio), após ``resolve_inbound_agent`` + grafo.
"""

import logging

logger = logging.getLogger(__name__)

_EMPTY_TWIML = "<Response></Response>"


class WhatsAppHandler:
    async def handle_webhook(self, payload: dict) -> str:
        from worker.tasks.inbound_handler import (
            process_inbound_message,
            try_claim_inbound_dedup,
        )

        body = (payload.get("Body") or "").strip()
        from_number = (payload.get("From") or "").strip()
        message_sid = (payload.get("MessageSid") or "").strip()

        if not body or not from_number:
            return _EMPTY_TWIML

        if message_sid and not try_claim_inbound_dedup("whatsapp", message_sid):
            logger.info(
                "WhatsApp webhook duplicado ignorado MessageSid=%s from=%s",
                message_sid,
                from_number,
            )
            return _EMPTY_TWIML

        # Sem MessageSid: processa sem dedup (Twilio pode reenviar o mesmo webhook).
        if not message_sid:
            logger.debug(
                "WhatsApp webhook sem MessageSid; dedup não aplicada (from=%s)",
                from_number,
            )

        process_inbound_message.delay(
            "whatsapp",
            from_number,
            body,
            message_sid or None,
        )
        logger.info(
            "WhatsApp inbound enfileirado from=%s message_sid=%s",
            from_number,
            message_sid or "(none)",
        )
        return _EMPTY_TWIML
