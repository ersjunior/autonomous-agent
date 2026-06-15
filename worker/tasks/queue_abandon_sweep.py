"""
Sweep de abandono na fila (R-B) — somente VOZ.

Mensageria (WhatsApp/Telegram) não tem abandono: contatos em WAITING permanecem
na fila até serem atendidos ou timeout de voz não se aplica.

Sem inbound de voz, esta task normalmente marca 0 entradas; permanece no Beat
para quando o canal voz receptivo existir.
"""

from __future__ import annotations

import logging

from app.core.database import AsyncSessionLocal
from app.services.queue_entry_service import sweep_voice_queue_abandonment
from worker.async_runner import run_celery_async
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _sweep_queue_abandonment_async() -> dict:
    async with AsyncSessionLocal() as session:
        count = await sweep_voice_queue_abandonment(session)
        await session.commit()
    return {"abandoned_marked": count, "channel_scope": "voice_only"}


@celery.task
def sweep_queue_abandonment() -> dict:
    """Beat: abandono na fila de espera (apenas voz)."""
    return run_celery_async(_sweep_queue_abandonment_async())
