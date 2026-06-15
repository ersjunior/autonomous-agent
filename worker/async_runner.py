"""Run async coroutines from Celery tasks with guaranteed resource cleanup.

Each Celery task uses ``asyncio.run`` (new event loop per task). Global SQLAlchemy
engines and asyncpg pgvector pools must be torn down **inside** the active loop
before it closes, or connections leak as idle sessions in Postgres.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def _cleanup_worker_async_resources() -> None:
    from agents.memory.pgvector_pool import dispose_pgvector_pools
    from agents.orchestrator.graph import reset_worker_async_clients
    from app.core.database import engine

    steps: list[tuple[str, Coroutine[object, object, object]]] = [
        ("pgvector_pools", dispose_pgvector_pools()),
        ("redis_short_term", reset_worker_async_clients()),
        ("sqlalchemy_engine", engine.dispose()),
    ]
    for name, step in steps:
        try:
            await step
        except Exception:
            logger.exception("Worker async cleanup failed: %s", name)


def run_celery_async(coro: Coroutine[object, object, T]) -> T:
    """Execute *coro* in a fresh event loop and always release DB/Redis/pgvector resources."""

    async def _wrapper() -> T:
        try:
            return await coro
        finally:
            await _cleanup_worker_async_resources()

    return asyncio.run(_wrapper())
