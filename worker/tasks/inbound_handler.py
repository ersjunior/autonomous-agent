"""Inbound message tasks — modo RECEPTIVO."""

import asyncio

from agents.orchestrator.router import get_response
from worker.celery_app import celery


async def _process_inbound_message(message: str, channel: str, user_id: str) -> str:
    return await get_response(message, channel, user_id, notify_received=True)


@celery.task(bind=True, max_retries=3)
def process_inbound_message(self, message: str, channel: str, user_id: str) -> str:
    """Processa mensagem recebida e retorna a resposta do agente."""
    try:
        return asyncio.run(_process_inbound_message(message, channel, user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc
