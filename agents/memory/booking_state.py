"""Estado Redis multi-turno para agendamento conversacional (WhatsApp/Telegram)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import redis

from app.core.activation_defaults import normalize_channel_type
from app.core.config import settings

logger = logging.getLogger(__name__)

BookingPhase = Literal["offering", "awaiting_choice", "confirming", "done"]

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def booking_state_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"booking:{ch}:{user_id}"


def get_booking_state(channel: str, user_id: str) -> dict[str, Any] | None:
    raw = _get_redis().get(booking_state_key(channel, user_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        logger.warning("Invalid booking state JSON channel=%s user_id=%s", channel, user_id)
        return None


def set_booking_state(channel: str, user_id: str, payload: dict[str, Any]) -> None:
    key = booking_state_key(channel, user_id)
    _get_redis().setex(
        key,
        settings.booking_state_ttl_seconds,
        json.dumps(payload, ensure_ascii=False),
    )


def clear_booking_state(channel: str, user_id: str) -> None:
    _get_redis().delete(booking_state_key(channel, user_id))


def is_active_booking_phase(phase: str | None) -> bool:
    return phase in ("offering", "awaiting_choice", "confirming")


def serialize_slot(starts_at: datetime, ends_at: datetime, label: str, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "starts_at": starts_at.astimezone(timezone.utc).isoformat(),
        "ends_at": ends_at.astimezone(timezone.utc).isoformat(),
        "label": label,
    }


def parse_slot(raw: dict[str, Any]) -> dict[str, Any]:
    """Normaliza slot do Redis para uso interno (datetime UTC)."""
    starts = datetime.fromisoformat(str(raw["starts_at"]))
    ends = datetime.fromisoformat(str(raw["ends_at"]))
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    return {
        "index": int(raw.get("index", 0)),
        "starts_at": starts.astimezone(timezone.utc),
        "ends_at": ends.astimezone(timezone.utc),
        "label": str(raw.get("label", "")),
    }
