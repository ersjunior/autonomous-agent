"""
Sweep de timeouts do handoff humano (H-2).

Beat (default 60s): devolve ao bot contatos não assumidos após queue_ttl;
auto-finaliza assumidos sem fechamento após finalize_ttl (NEG:ABANDONO).
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal, engine
from app.services.human_handoff import sweep_human_handoff_timeouts
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _sweep_human_handoff_async() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        stats = await sweep_human_handoff_timeouts(session)
        await session.commit()
    return stats


@celery.task
def sweep_human_handoff_timeouts_task() -> dict[str, int]:
    """Beat: timeouts de fila humana (queue) e finalização (assumido)."""

    async def _wrapper() -> dict[str, int]:
        from agents.orchestrator.graph import reset_worker_async_clients

        try:
            return await _sweep_human_handoff_async()
        finally:
            await reset_worker_async_clients()
            await engine.dispose()

    result = asyncio.run(_wrapper())
    if result.get("returned_to_bot") or result.get("auto_finalized"):
        logger.info("human_handoff_sweep: %s", result)
    return result
