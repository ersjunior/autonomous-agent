"""
Processador da fila receptiva (R-A) — Celery Beat.

Intervalo: ``settings.receptive_queue_beat_seconds`` (default 30s).

Para cada canal messaging com fila não vazia, enquanto houver capacidade global+slot
e itens na fila, faz dequeue FIFO e atende (``attend_from_queue_payload``).
"""

from __future__ import annotations

import logging

from app.core.activation_defaults import MESSAGING_CHANNELS
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.activation_service import get_agent_channel_settings_row, merged_params
from app.services.capacity_service import (
    current_global_usage,
    try_acquire_receptive_capacity,
)
from app.services.inbound_attendance import attend_from_queue_payload
from app.services.receptive_queue import dequeue_next, queue_size
from app.services.receptive_window import is_receptive_window_open
from worker.async_runner import run_celery_async
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _process_receptive_queue_async() -> dict:
    stats: dict = {
        "channels": {},
        "dequeued": 0,
        "served": 0,
        "skipped_no_capacity": 0,
        "skipped_window": 0,
        "global_usage_end": 0,
    }

    async with AsyncSessionLocal() as session:
        for channel in sorted(MESSAGING_CHANNELS):
            ch_stats = {"queue_size": queue_size(channel), "served": 0}
            stats["channels"][channel] = ch_stats

            while queue_size(channel) > 0:
                payload = dequeue_next(channel)
                if payload is None:
                    break

                stats["dequeued"] += 1

                from sqlalchemy import select
                from uuid import UUID

                from app.models.agent import Agent

                agent_result = await session.execute(
                    select(Agent).where(Agent.id == UUID(payload.agent_id))
                )
                agent = agent_result.scalar_one_or_none()
                if agent is None:
                    logger.warning(
                        "Fila receptiva: agente %s ausente; item descartado",
                        payload.agent_id,
                    )
                    continue

                row = await get_agent_channel_settings_row(session, agent.id, channel)
                params = merged_params(channel, row.params if row else None)

                if not is_receptive_window_open(params):
                    stats["skipped_window"] += 1
                    logger.info(
                        "Fila receptiva: fora da janela; re-enfileirando %s",
                        payload.user_id,
                    )
                    from app.services.receptive_queue import enqueue_receptive

                    enqueue_receptive(
                        channel,
                        payload.user_id,
                        message=payload.message,
                        agent_id=payload.agent_id,
                        message_sid=payload.message_sid,
                        enqueued_at=payload.enqueued_at,
                    )
                    break

                capacity = try_acquire_receptive_capacity(str(agent.id), channel, params)
                if capacity is None:
                    stats["skipped_no_capacity"] += 1
                    from app.services.receptive_queue import enqueue_receptive

                    enqueue_receptive(
                        channel,
                        payload.user_id,
                        message=payload.message,
                        agent_id=payload.agent_id,
                        message_sid=payload.message_sid,
                        enqueued_at=payload.enqueued_at,
                    )
                    break

                try:
                    await attend_from_queue_payload(session, payload, capacity)
                    await session.commit()
                    stats["served"] += 1
                    ch_stats["served"] += 1
                    logger.info(
                        "Fila receptiva: atendido channel=%s user=%s (FIFO score=%s)",
                        channel,
                        payload.user_id,
                        payload.enqueued_at,
                    )
                except Exception:
                    await session.rollback()
                    release_capacity = capacity
                    from app.services.capacity_service import release_global, release_slot

                    release_slot(
                        release_capacity.agent_id,
                        channel,
                        release_capacity.slot_token,
                    )
                    release_global(release_capacity.global_token, release_capacity.weight)
                    from app.services.receptive_queue import enqueue_receptive

                    enqueue_receptive(
                        channel,
                        payload.user_id,
                        message=payload.message,
                        agent_id=payload.agent_id,
                        message_sid=payload.message_sid,
                        enqueued_at=payload.enqueued_at,
                    )
                    raise

    stats["global_usage_end"] = current_global_usage()
    return stats


@celery.task
def process_receptive_queue() -> dict:
    """Beat: processa fila receptiva FIFO quando há capacidade."""
    return run_celery_async(_process_receptive_queue_async())
