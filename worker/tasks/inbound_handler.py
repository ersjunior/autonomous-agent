"""Inbound message tasks — modo RECEPTIVO / roteamento ACTIVE quando conversa aberta."""

import asyncio
import logging

from agents.orchestrator.router import route_message
from app.core.database import AsyncSessionLocal
from worker.celery_app import celery
from worker.tasks.conversation_routing import agent_routing_metadata, resolve_inbound_agent
from worker.tasks.lead_tracking import find_lead_by_channel_user, track_inbound_lead_interaction

logger = logging.getLogger(__name__)


async def _process_inbound_message(message: str, channel: str, user_id: str) -> str:
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()

    async with AsyncSessionLocal() as session:
        lead = await find_lead_by_channel_user(session, channel, user_id)
        agent = await resolve_inbound_agent(session, lead, channel)
        agent_context = agent_routing_metadata(agent)

        logger.info(
            "Inbound atendido por agente %s (%s) channel=%s user_id=%s lead=%s",
            agent.name,
            agent.mode.value,
            channel,
            user_id,
            lead.id if lead else None,
        )

        result = await route_message(
            message,
            channel,
            user_id,
            notify_received=True,
            agent_context=agent_context,
        )

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
    try:
        return asyncio.run(_process_inbound_message(message, channel, user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc
