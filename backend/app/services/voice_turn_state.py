"""Estado Redis de turnos de voz inbound (processamento assíncrono pós-Record)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

VOICE_TURN_TTL_SECONDS = 2 * 3600

TurnStatus = Literal[
    "pending",
    "ready",
    "error",
    "silence_stt",
    "consumed",
]

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _turn_key(call_sid: str, turn_id: str) -> str:
    return f"voice_turn:{(call_sid or '').strip()}:{(turn_id or '').strip()}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pending_turn(
    *,
    call_sid: str,
    turn_id: str,
    recording_url: str,
    from_number: str,
) -> dict[str, Any]:
    """Registra turno pendente e dispara processamento externo (Celery)."""
    sid = (call_sid or "").strip()
    tid = (turn_id or "").strip()
    payload: dict[str, Any] = {
        "status": "pending",
        "recording_url": (recording_url or "").strip(),
        "from_number": (from_number or "").strip(),
        "created_at": _utc_now_iso(),
        "poll_count": 0,
    }
    _get_redis().setex(
        _turn_key(sid, tid),
        VOICE_TURN_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=False),
    )
    logger.info("Voice turn pending call_sid=%s turn_id=%s", sid, tid)
    return payload


def get_voice_turn(call_sid: str, turn_id: str) -> dict[str, Any] | None:
    sid = (call_sid or "").strip()
    tid = (turn_id or "").strip()
    if not sid or not tid:
        return None
    raw = _get_redis().get(_turn_key(sid, tid))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _save_turn(call_sid: str, turn_id: str, payload: dict[str, Any]) -> None:
    sid = (call_sid or "").strip()
    tid = (turn_id or "").strip()
    _get_redis().setex(
        _turn_key(sid, tid),
        VOICE_TURN_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=False),
    )


def increment_turn_poll_count(call_sid: str, turn_id: str) -> int:
    """Incrementa contador de polling (turn-ready pending loop). Retorna novo valor."""
    data = get_voice_turn(call_sid, turn_id)
    if not data:
        return 0
    count = int(data.get("poll_count") or 0) + 1
    data["poll_count"] = count
    _save_turn(call_sid, turn_id, data)
    return count


def mark_turn_ready(
    call_sid: str,
    turn_id: str,
    *,
    audio_filename: str,
    should_hangup: bool = False,
) -> None:
    data = get_voice_turn(call_sid, turn_id) or {}
    data["status"] = "ready"
    data["audio_filename"] = (audio_filename or "").strip()
    data["should_hangup"] = bool(should_hangup)
    data["ready_at"] = _utc_now_iso()
    _save_turn(call_sid, turn_id, data)
    logger.info(
        "Voice turn ready call_sid=%s turn_id=%s audio=%s hangup=%s",
        call_sid,
        turn_id,
        audio_filename,
        should_hangup,
    )


def mark_turn_error(
    call_sid: str,
    turn_id: str,
    *,
    error: str,
) -> None:
    data = get_voice_turn(call_sid, turn_id) or {}
    data["status"] = "error"
    data["error"] = (error or "unknown")[:500]
    data["error_at"] = _utc_now_iso()
    _save_turn(call_sid, turn_id, data)
    logger.warning(
        "Voice turn error call_sid=%s turn_id=%s error=%s",
        call_sid,
        turn_id,
        data["error"],
    )


def mark_turn_silence_stt(call_sid: str, turn_id: str) -> None:
    data = get_voice_turn(call_sid, turn_id) or {}
    data["status"] = "silence_stt"
    data["silence_at"] = _utc_now_iso()
    _save_turn(call_sid, turn_id, data)
    logger.info("Voice turn silence_stt call_sid=%s turn_id=%s", call_sid, turn_id)


def mark_turn_consumed(call_sid: str, turn_id: str) -> None:
    data = get_voice_turn(call_sid, turn_id)
    if not data:
        return
    data["status"] = "consumed"
    data["consumed_at"] = _utc_now_iso()
    _save_turn(call_sid, turn_id, data)


def delete_voice_turn(call_sid: str, turn_id: str) -> None:
    sid = (call_sid or "").strip()
    tid = (turn_id or "").strip()
    if sid and tid:
        _get_redis().delete(_turn_key(sid, tid))
