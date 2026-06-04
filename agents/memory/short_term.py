"""Short-term memory (Redis)."""

import json

import redis.asyncio as redis

from app.core.config import settings

CHAT_KEY_PREFIX = "chat:"
TTL_SECONDS = 3600


class ShortTermMemory:
    """Stores conversation history in Redis with a 1-hour TTL."""

    def __init__(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    @staticmethod
    def _key(user_id: str) -> str:
        return f"{CHAT_KEY_PREFIX}{user_id}"

    async def get_history(self, user_id: str) -> list[dict]:
        data = await self._redis.get(self._key(user_id))
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

    async def save_history(self, user_id: str, history: list[dict]) -> None:
        cleaned = self._sanitize_history(history)
        await self._redis.set(
            self._key(user_id),
            json.dumps(cleaned),
            ex=TTL_SECONDS,
        )

    async def clear_history(self, user_id: str) -> None:
        await self._redis.delete(self._key(user_id))
