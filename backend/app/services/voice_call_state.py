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
    accumulated_silence_sec: float | None = None,
) -> None:
    sid = (call_sid or "").strip()
    if not sid:
        return
    existing = get_voice_call_state(sid) or {}
    payload: dict[str, Any] = {"silence_stage": int(silence_stage)}
    if accumulated_silence_sec is not None:
        payload["accumulated_silence_sec"] = float(accumulated_silence_sec)
    elif "accumulated_silence_sec" in existing:
        payload["accumulated_silence_sec"] = existing["accumulated_silence_sec"]
    from_n = (from_number or existing.get("from_number") or "").strip() or None
    if from_n:
        payload["from_number"] = from_n
    _get_redis().setex(
        _state_key(sid),
        VOICE_CALL_STATE_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=False),
    )


def get_accumulated_silence_sec(call_sid: str) -> float:
    data = get_voice_call_state(call_sid)
    if not data:
        return 0.0
    try:
        return float(data.get("accumulated_silence_sec", 0))
    except (TypeError, ValueError):
        return 0.0


def add_accumulated_silence(
    call_sid: str,
    delta_sec: float,
    *,
    from_number: str | None = None,
) -> float:
    """Soma intervalo de silêncio (≈ timeout do Record) e retorna total acumulado."""
    sid = (call_sid or "").strip()
    if not sid or delta_sec <= 0:
        return get_accumulated_silence_sec(sid)
    data = get_voice_call_state(sid) or {}
    stage = get_silence_stage(sid)
    accumulated = get_accumulated_silence_sec(sid) + float(delta_sec)
    from_n = (from_number or data.get("from_number") or "").strip() or None
    payload: dict[str, Any] = {
        "silence_stage": stage,
        "accumulated_silence_sec": accumulated,
    }
    if from_n:
        payload["from_number"] = from_n
    _get_redis().setex(
        _state_key(sid),
        VOICE_CALL_STATE_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=False),
    )
    return accumulated


def reset_silence_stage(call_sid: str, *, from_number: str | None = None) -> None:
    """Volta ao estágio normal após fala válida do cliente."""
    set_voice_call_state(
        call_sid,
        silence_stage=0,
        from_number=from_number,
        accumulated_silence_sec=0.0,
    )


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
