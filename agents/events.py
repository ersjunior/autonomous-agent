"""Agent event publishing for real-time monitoring via Redis pub/sub."""

import json
from datetime import datetime, timezone

import redis
import redis.asyncio as aioredis

from app.core.config import settings

AGENT_EVENTS_CHANNEL = "agent_events"


def _build_event(event_type: str, payload: dict) -> str:
    event = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    return json.dumps(event)


def publish_event(event_type: str, payload: dict) -> None:
    """Publish a monitoring event (sync — safe from Celery tasks)."""
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.publish(AGENT_EVENTS_CHANNEL, _build_event(event_type, payload))
    finally:
        client.close()


async def publish_event_async(event_type: str, payload: dict) -> None:
    """Publish a monitoring event (async — for graph nodes and FastAPI)."""
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.publish(AGENT_EVENTS_CHANNEL, _build_event(event_type, payload))
    finally:
        await client.aclose()
