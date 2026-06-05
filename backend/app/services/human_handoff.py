"""
Modo humano (B-2) — contato escalado para atendente; bot para de responder.

Chaves Redis:
  human_mode:{channel}:{user_id}           — timestamp ISO do escalonamento (TTL = timeout)
  human_mode_notified:{channel}:{user_id}  — throttle da mensagem ocasional de espera

Política:
  - Escopo por contato (channel + user_id), independente de ACTIVE/RECEPTIVE.
  - Gatilho de entrada: escalonamento no fluxo inbound (should_escalate).
  - Saída: TTL expira (volta ao bot) OU reativação manual (exit_human_mode).
  - Enquanto ativo: inbound não chama grafo/LLM; mensagem ocasional de fila humana.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import redis

from app.core.activation_defaults import normalize_channel_type
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

HUMAN_MODE_WAIT_MESSAGE = (
    "Seu atendimento está na fila de atendimento humano, "
    "em breve um atendente prosseguirá."
)


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _human_mode_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"human_mode:{ch}:{user_id}"


def _notify_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"human_mode_notified:{ch}:{user_id}"


def _parse_human_mode_key(key: str) -> tuple[str, str] | None:
    prefix = "human_mode:"
    if not key.startswith(prefix):
        return None
    rest = key[len(prefix) :]
    if ":" not in rest:
        return None
    channel, user_id = rest.split(":", 1)
    return channel, user_id


def enter_human_mode(channel: str, user_id: str) -> None:
    """Marca contato em modo humano com TTL de segurança."""
    ch = normalize_channel_type(channel)
    payload = json.dumps(
        {"escalated_at": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False,
    )
    ttl = settings.human_mode_ttl_seconds
    _get_redis().set(_human_mode_key(ch, user_id), payload, ex=ttl)
    logger.info(
        "Modo humano ativado channel=%s user=%s ttl=%ss",
        ch,
        user_id,
        ttl,
    )


def is_in_human_mode(channel: str, user_id: str) -> bool:
    """True enquanto a chave existir no Redis (TTL não expirou)."""
    ch = normalize_channel_type(channel)
    return bool(_get_redis().exists(_human_mode_key(ch, user_id)))


def exit_human_mode(channel: str, user_id: str) -> bool:
    """Reativação manual — remove modo humano e throttle de notificação."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    removed = client.delete(_human_mode_key(ch, user_id))
    client.delete(_notify_key(ch, user_id))
    if removed:
        logger.info("Modo humano encerrado (manual) channel=%s user=%s", ch, user_id)
    return bool(removed)


def should_send_waiting_message(channel: str, user_id: str) -> bool:
    """
    Controla frequência da mensagem ocasional.
    Retorna True se deve enviar agora; seta chave de throttle com TTL curto.
    """
    ch = normalize_channel_type(channel)
    client = _get_redis()
    nkey = _notify_key(ch, user_id)
    interval = settings.human_mode_notify_interval_seconds
    if client.exists(nkey):
        return False
    client.set(nkey, str(time.time()), ex=interval)
    return True


def get_human_mode_escalated_at(channel: str, user_id: str) -> datetime | None:
    ch = normalize_channel_type(channel)
    raw = _get_redis().get(_human_mode_key(ch, user_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        ts = data.get("escalated_at")
        if ts:
            return datetime.fromisoformat(str(ts))
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def handle_human_mode_inbound(channel: str, user_id: str) -> tuple[bool, str | None]:
    """
    Curto-circuito do inbound enquanto em modo humano.

    Returns:
        (handled, message_to_send) — message_to_send é None se throttle ativo.
    """
    if not is_in_human_mode(channel, user_id):
        return False, None

    msg: str | None = None
    if should_send_waiting_message(channel, user_id):
        msg = HUMAN_MODE_WAIT_MESSAGE

    logger.info(
        "Modo humano: inbound curto-circuitado channel=%s user=%s notify=%s",
        normalize_channel_type(channel),
        user_id,
        msg is not None,
    )
    return True, msg


def list_active_human_mode_contacts() -> list[dict[str, Any]]:
    """Lista contatos com human_mode:* ativo (para painel)."""
    client = _get_redis()
    contacts: list[dict[str, Any]] = []
    for key in client.scan_iter("human_mode:*", count=100):
        parsed = _parse_human_mode_key(key)
        if parsed is None:
            continue
        channel, uid = parsed
        ttl = client.ttl(key)
        escalated_at = get_human_mode_escalated_at(channel, uid)
        contacts.append(
            {
                "channel": channel,
                "user_id": uid,
                "escalated_at": escalated_at.isoformat() if escalated_at else None,
                "ttl_seconds": ttl if ttl >= 0 else None,
            }
        )
    contacts.sort(key=lambda c: c.get("escalated_at") or "", reverse=True)
    return contacts
