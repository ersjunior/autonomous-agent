"""
Hot-reload sync for provider settings across backend and Celery worker.

- Backend: call ``ensure_settings_fresh_async`` before serving settings or using providers.
- Worker: call ``ensure_settings_fresh_async`` inside the task coroutine (same ``asyncio.run``),
  not ``ensure_settings_fresh_sync`` before it (avoids nested loops / stale asyncpg connections).
- ``update_settings`` increments Redis key ``settings_version`` and publishes ``settings_invalidate``.
- Processes compare the Redis version; on change (or every ``TTL_SECONDS`` fallback), reload from DB.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.database import AsyncSessionLocal
from app.services.settings_service import (
    SETTINGS_VERSION_KEY,
    get_redis_settings_version,
    load_into_settings,
)

logger = logging.getLogger(__name__)

TTL_SECONDS = 30

_local_version: int | None = None
_last_check_monotonic: float = 0.0


def mark_local_version(version: int) -> None:
    global _local_version, _last_check_monotonic
    _local_version = version
    _last_check_monotonic = time.monotonic()


def _needs_reload(remote_version: int) -> bool:
    global _local_version, _last_check_monotonic
    now = time.monotonic()
    if _local_version is None:
        return True
    if remote_version != _local_version:
        return True
    if now - _last_check_monotonic >= TTL_SECONDS:
        return True
    return False


async def _reload_from_database() -> None:
    async with AsyncSessionLocal() as session:
        await load_into_settings(session)
    mark_local_version(get_redis_settings_version())


async def ensure_settings_fresh_async() -> None:
    """Reload settings from DB when Redis version changed or TTL elapsed."""
    try:
        remote_version = get_redis_settings_version()
    except Exception:
        logger.exception("Failed to read settings version from Redis; reloading from DB")
        await _reload_from_database()
        return

    if not _needs_reload(remote_version):
        return

    await _reload_from_database()


def ensure_settings_fresh_sync() -> None:
    """Sync entry point for Celery tasks."""
    try:
        remote_version = get_redis_settings_version()
    except Exception:
        logger.exception("Failed to read settings version from Redis; reloading from DB")
        asyncio.run(_reload_from_database())
        return

    if not _needs_reload(remote_version):
        return

    asyncio.run(_reload_from_database())


async def bootstrap_settings() -> None:
    """Seed from env if needed and load DB values into the singleton (startup)."""
    from app.services.settings_service import (
        SETTINGS_VERSION_KEY,
        _get_redis,
        seed_from_env_if_empty,
        seed_missing_settings,
    )

    async with AsyncSessionLocal() as session:
        await seed_from_env_if_empty(session)
        await seed_missing_settings(session)
        await load_into_settings(session)

    try:
        client = _get_redis()
        if client.get(SETTINGS_VERSION_KEY) is None:
            client.set(SETTINGS_VERSION_KEY, 0)
        mark_local_version(get_redis_settings_version())
    except Exception:
        mark_local_version(0)
