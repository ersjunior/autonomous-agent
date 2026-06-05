"""
Fila receptiva FIFO (R-A) — Redis ZSET + payload por contato.

Chaves:
  receptive_queue:{channel}           — ZSET member={channel}:{user_id}, score=enqueued_at
  queue_payload:{channel}:{user_id}   — JSON (message, agent_id, message_sid, enqueued_at)

FIFO: menor score = entrou primeiro. Idempotência: mesmo (channel, user_id) não duplica
entrada no ZSET (ZADD NX); payload é atualizado com a mensagem mais recente.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import redis

from app.core.activation_defaults import MESSAGING_CHANNELS, normalize_channel_type
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

_LUA_DEQUEUE_NEXT = """
local queue_key = KEYS[1]
local payload_prefix = ARGV[1]

local members = redis.call('ZRANGE', queue_key, 0, 0)
if #members == 0 then
  return {}
end
local member = members[1]
redis.call('ZREM', queue_key, member)

local colon = string.find(member, ':', 1, true)
if colon == nil then
  return {member, ''}
end
local channel = string.sub(member, 1, colon - 1)
local user_id = string.sub(member, colon + 1)
local payload_key = payload_prefix .. channel .. ':' .. user_id
local payload = redis.call('GET', payload_key)
redis.call('DEL', payload_key)
return {member, payload or ''}
"""


@dataclass
class QueuePayload:
    user_id: str
    channel: str
    message: str
    agent_id: str
    message_sid: str | None
    enqueued_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "channel": self.channel,
            "message": self.message,
            "agent_id": self.agent_id,
            "message_sid": self.message_sid,
            "enqueued_at": self.enqueued_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuePayload:
        return cls(
            user_id=str(data["user_id"]),
            channel=str(data["channel"]),
            message=str(data.get("message") or ""),
            agent_id=str(data["agent_id"]),
            message_sid=data.get("message_sid"),
            enqueued_at=float(data.get("enqueued_at") or time.time()),
        )


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def queue_member(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"{ch}:{user_id}"


def _queue_key(channel: str) -> str:
    return f"receptive_queue:{normalize_channel_type(channel)}"


def _payload_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"queue_payload:{ch}:{user_id}"


def _parse_member(member: str) -> tuple[str, str] | None:
    if ":" not in member:
        return None
    channel, user_id = member.split(":", 1)
    return channel, user_id


def enqueue_receptive(
    channel: str,
    user_id: str,
    *,
    message: str,
    agent_id: str,
    message_sid: str | None = None,
    enqueued_at: float | None = None,
) -> bool:
    """
    Enfileira contato. Retorna True se nova entrada no ZSET; False se já estava na fila
    (payload atualizado com mensagem mais recente).
    """
    ch = normalize_channel_type(channel)
    if ch not in MESSAGING_CHANNELS:
        raise ValueError(f"Canal não suportado na fila receptiva: {channel}")

    member = queue_member(ch, user_id)
    score = enqueued_at if enqueued_at is not None else time.time()
    client = _get_redis()

    added = bool(
        client.zadd(_queue_key(ch), {member: score}, nx=True)
    )
    existing_raw = client.get(_payload_key(ch, user_id))
    if existing_raw:
        try:
            existing = json.loads(existing_raw)
            score = float(existing.get("enqueued_at", score))
        except json.JSONDecodeError:
            pass

    payload = QueuePayload(
        user_id=user_id,
        channel=ch,
        message=message,
        agent_id=agent_id,
        message_sid=message_sid,
        enqueued_at=score,
    )
    client.set(
        _payload_key(ch, user_id),
        json.dumps(payload.to_dict()),
        ex=settings.receptive_queue_payload_ttl_seconds,
    )
    if not added:
        logger.info(
            "Fila receptiva: atualizado payload (já na fila) channel=%s user=%s",
            ch,
            user_id,
        )
    return added


def dequeue_next(channel: str) -> QueuePayload | None:
    """Remove e retorna o contato com menor score (FIFO). Atômico (Lua)."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    raw = client.eval(
        _LUA_DEQUEUE_NEXT,
        1,
        _queue_key(ch),
        "queue_payload:",
    )
    if not raw or len(raw) < 2:
        return None
    member, payload_json = raw[0], raw[1]
    if not payload_json:
        parsed = _parse_member(member)
        if not parsed:
            return None
        ch_p, user_id = parsed
        return QueuePayload(
            user_id=user_id,
            channel=ch_p,
            message="",
            agent_id="",
            message_sid=None,
            enqueued_at=time.time(),
        )
    data = json.loads(payload_json)
    return QueuePayload.from_dict(data)


def queue_size(channel: str) -> int:
    return int(_get_redis().zcard(_queue_key(channel)))


def is_in_queue(channel: str, user_id: str) -> bool:
    ch = normalize_channel_type(channel)
    rank = _get_redis().zrank(_queue_key(ch), queue_member(ch, user_id))
    return rank is not None


def remove_from_queue(channel: str, user_id: str) -> bool:
    ch = normalize_channel_type(channel)
    client = _get_redis()
    member = queue_member(ch, user_id)
    removed = int(client.zrem(_queue_key(ch), member))
    client.delete(_payload_key(ch, user_id))
    return removed > 0


def list_queue_members(channel: str, limit: int = 20) -> list[tuple[str, float]]:
    """Debug/test: (member, score) ordenado FIFO."""
    ch = normalize_channel_type(channel)
    return [
        (m, float(s))
        for m, s in _get_redis().zrange(_queue_key(ch), 0, limit - 1, withscores=True)
    ]
