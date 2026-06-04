"""Inbound message tasks — modo RECEPTIVO."""

import asyncio

from agents.orchestrator.router import route_message
from app.core.database import AsyncSessionLocal
from worker.celery_app import celery
from worker.tasks.lead_tracking import track_inbound_lead_interaction


async def _process_inbound_message(message: str, channel: str, user_id: str) -> str:
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()
    result = await route_message(message, channel, user_id, notify_received=True)

    async with AsyncSessionLocal() as session:
        await track_inbound_lead_interaction(
            session,
            channel,
            user_id,
            message,
            result.get("intent", "other"),
        )
        await session.commit()

    return result.get("response", "")


@celery.task(bind=True, max_retries=3)
def process_inbound_message(self, message: str, channel: str, user_id: str) -> str:
    """Processa mensagem recebida e retorna a resposta do agente."""
    from app.services.settings_sync import ensure_settings_fresh_sync

    ensure_settings_fresh_sync()
    try:
        return asyncio.run(_process_inbound_message(message, channel, user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc
