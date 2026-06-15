"""Rastreamento de status de entrega WhatsApp (Twilio status callback)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_interaction import LeadInteraction

logger = logging.getLogger(__name__)

WHATSAPP_STATUS_CALLBACK_PATH = "/api/v1/channels/webhooks/whatsapp/status"

TERMINAL_SUCCESS = frozenset({"delivered", "read"})
TERMINAL_FAILURE = frozenset({"undelivered", "failed"})

# Ordem aproximada para callbacks fora de ordem (falha terminal vence intermediários).
_STATUS_RANK: dict[str, int] = {
    "queued": 1,
    "accepted": 1,
    "sending": 2,
    "sent": 3,
    "delivering": 4,
    "receiving": 4,
    "delivered": 5,
    "read": 6,
    "undelivered": 100,
    "failed": 101,
}

TWILIO_ERROR_LABELS: dict[str, str] = {
    "63015": "sem opt-in no sandbox",
    "63016": "fora da janela de 24h",
    "63007": "número inválido para WhatsApp",
    "63003": "conta sem permissão para o destino",
    "21211": "número de destino inválido",
    "21610": "destinatário bloqueou mensagens",
}


def normalize_delivery_status(raw: str | None) -> str:
    return (raw or "").strip().lower()


def delivery_status_rank(status: str | None) -> int:
    return _STATUS_RANK.get(normalize_delivery_status(status), 0)


def should_apply_delivery_update(current: str | None, new: str) -> bool:
    """Idempotente: não regride de terminal; falha terminal vence intermediário."""
    cur = normalize_delivery_status(current)
    nxt = normalize_delivery_status(new)
    if not nxt:
        return False
    if cur == nxt:
        return True
    if cur in TERMINAL_FAILURE:
        return nxt in TERMINAL_FAILURE
    if cur in TERMINAL_SUCCESS:
        return nxt in TERMINAL_SUCCESS and delivery_status_rank(nxt) >= delivery_status_rank(cur)
    if nxt in TERMINAL_FAILURE:
        return True
    return delivery_status_rank(nxt) >= delivery_status_rank(cur)


def delivery_badge_label(
    status: str | None,
    error_code: str | None = None,
) -> str | None:
    """Rótulo amigável para UI (separado do status de atendimento)."""
    st = normalize_delivery_status(status)
    if not st:
        return None
    if st in TERMINAL_SUCCESS:
        return "Entregue"
    if st in TERMINAL_FAILURE:
        hint = TWILIO_ERROR_LABELS.get((error_code or "").strip(), None)
        if hint:
            return f"Falhou ({hint})"
        if error_code:
            return f"Falhou (código {error_code})"
        return "Falhou"
    return "Enviado"


async def apply_whatsapp_delivery_status(
    session: AsyncSession,
    *,
    message_sid: str,
    message_status: str,
    error_code: str | None = None,
) -> bool:
    """
    Atualiza LI correlacionada pelo ``twilio_message_sid``.

    Retorna True se encontrou e aplicou (ou ignorou por idempotência com log).
    """
    sid = (message_sid or "").strip()
    new_status = normalize_delivery_status(message_status)
    if not sid or not new_status:
        logger.warning(
            "WhatsApp status callback ignorado: sid=%r status=%r",
            message_sid,
            message_status,
        )
        return False

    result = await session.execute(
        select(LeadInteraction).where(LeadInteraction.twilio_message_sid == sid).limit(1)
    )
    record = result.scalar_one_or_none()
    if record is None:
        logger.info(
            "WhatsApp delivery status %s sid=%s — LI não encontrada (callback ignorado)",
            new_status,
            sid,
        )
        return False

    current = record.last_delivery_status
    if not should_apply_delivery_update(current, new_status):
        logger.debug(
            "WhatsApp delivery status ignorado (sem regressão) sid=%s current=%s new=%s",
            sid,
            current,
            new_status,
        )
        return True

    record.last_delivery_status = new_status
    if new_status in TERMINAL_FAILURE and error_code:
        record.last_delivery_error_code = str(error_code).strip()
    elif new_status in TERMINAL_SUCCESS:
        record.last_delivery_error_code = None

    await session.flush()

    err = (error_code or "").strip()
    if new_status in TERMINAL_FAILURE:
        logger.warning(
            "WhatsApp delivery FAILED sid=%s status=%s error_code=%s li=%s lead=%s",
            sid,
            new_status,
            err or "?",
            record.id,
            record.lead_id,
        )
    elif new_status in TERMINAL_SUCCESS:
        logger.info(
            "WhatsApp delivery DELIVERED sid=%s status=%s li=%s lead=%s",
            sid,
            new_status,
            record.id,
            record.lead_id,
        )
    else:
        logger.info(
            "WhatsApp delivery status=%s sid=%s li=%s (aguardando entrega)",
            new_status,
            sid,
            record.id,
        )

    return True
