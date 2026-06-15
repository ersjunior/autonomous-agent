"""Estado Redis por chamada de voz inbound (silêncio consecutivo)."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

VOICE_CALL_STATE_TTL_SECONDS = 2 * 3600

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _state_key(call_sid: str) -> str:
    return f"voice_call_state:{(call_sid or '').strip()}"


def get_voice_call_state(call_sid: str) -> dict[str, Any] | None:
    """Retorna payload JSON ou None."""
    sid = (call_sid or "").strip()
    if not sid:
        return None
    raw = _get_redis().get(_state_key(sid))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def get_silence_stage(call_sid: str) -> int:
    """0 = normal; 1 = aviso de silêncio já enviado nesta chamada."""
    data = get_voice_call_state(call_sid)
    if not data:
        return 0
    try:
        return int(data.get("silence_stage", 0))
    except (TypeError, ValueError):
        return 0


def set_voice_call_state(
    call_sid: str,
    *,
    silence_stage: int,
    from_number: str | None = None,
) -> None:
    sid = (call_sid or "").strip()
    if not sid:
        return
    payload: dict[str, Any] = {"silence_stage": int(silence_stage)}
    if from_number:
        payload["from_number"] = from_number.strip()
    _get_redis().setex(
        _state_key(sid),
        VOICE_CALL_STATE_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=False),
    )


def reset_silence_stage(call_sid: str, *, from_number: str | None = None) -> None:
    """Volta ao estágio normal após fala válida do cliente."""
    set_voice_call_state(call_sid, silence_stage=0, from_number=from_number)


def clear_voice_call_state(call_sid: str) -> None:
    sid = (call_sid or "").strip()
    if sid:
        _get_redis().delete(_state_key(sid))


def remember_call_from_number(call_sid: str, from_number: str) -> None:
    """Preserva telefone do cliente no Redis sem alterar silence_stage."""
    stage = get_silence_stage(call_sid)
    set_voice_call_state(call_sid, silence_stage=stage, from_number=from_number)


def get_call_customer_number(call_sid: str) -> str | None:
    """Telefone do cliente (lead) associado à chamada, se conhecido no Redis."""
    data = get_voice_call_state(call_sid)
    if not data:
        return None
    raw = (data.get("from_number") or "").strip()
    return raw or None
