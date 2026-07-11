"""Short-term memory (Redis)."""

import json

import redis.asyncio as redis

from app.core.config import settings

CHAT_KEY_PREFIX = "chat:"
TTL_SECONDS = 3600
# Voice dialog history is keyed by Twilio CallSid; TTL avoids stale keys after the call ends.
VOICE_CALL_HISTORY_TTL_SECONDS = 4 * 3600


def conversation_memory_key(
    channel: str,
    user_id: str,
    *,
    twilio_call_sid: str | None = None,
) -> str:
    """
    Redis suffix for short-term dialog history (full key: ``chat:{suffix}``).

    Voice: one isolated thread per call (``twilio_call_sid``). Other channels: per contact ``user_id``.
    """
    ch = (channel or "").lower()
    sid = (twilio_call_sid or "").strip()
    if ch == "voice" and sid:
        return sid
    return user_id


def _history_ttl_seconds(channel: str | None) -> int:
    if (channel or "").lower() == "voice":
        return VOICE_CALL_HISTORY_TTL_SECONDS
    return TTL_SECONDS


class ShortTermMemory:
    """Stores conversation history in Redis with a 1-hour TTL (voice calls: 4-hour TTL per CallSid)."""

    def __init__(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    @staticmethod
    def _key(memory_key: str) -> str:
        return f"{CHAT_KEY_PREFIX}{memory_key}"

    async def get_history(self, memory_key: str, *, channel: str | None = None) -> list[dict]:
        data = await self._redis.get(self._key(memory_key))
        if data is None:
            return []
        return json.loads(data)

    @staticmethod
    def _sanitize_history(history: list[dict]) -> list[dict]:
        """Drop assistant turns with empty content (legacy polluted history)."""
        sanitized: list[dict] = []
        for item in history:
            role = item.get("role", "")
            content = item.get("content", "")
            if role in ("assistant", "ai", "agent") and not str(content).strip():
                continue
            sanitized.append(item)
        return sanitized

    async def save_history(
        self,
        memory_key: str,
        history: list[dict],
        *,
        channel: str | None = None,
    ) -> None:
        cleaned = self._sanitize_history(history)
        await self._redis.set(
            self._key(memory_key),
            json.dumps(cleaned),
            ex=_history_ttl_seconds(channel),
        )

    async def clear_history(self, memory_key: str) -> None:
        await self._redis.delete(self._key(memory_key))
