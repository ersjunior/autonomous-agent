"""Inbound message tasks — modo RECEPTIVO."""

import asyncio

from agents.events import publish_event_async
from agents.orchestrator.graph import AgentState, agent_graph
from worker.celery_app import celery


async def _process_inbound_message(message: str, channel: str, user_id: str) -> str:
    await publish_event_async(
        "message_received",
        {
            "channel": channel,
            "user_id": user_id,
            "message": message,
        },
    )

    state: AgentState = {
        "message": message,
        "channel": channel.lower(),
        "user_id": user_id,
        "intent": "",
        "confidence": 0.0,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
    }

    result = await agent_graph.ainvoke(state)
    return result.get("response", "")


@celery.task(bind=True, max_retries=3)
def process_inbound_message(self, message: str, channel: str, user_id: str) -> str:
    """Processa mensagem recebida e retorna a resposta do agente."""
    try:
        return asyncio.run(_process_inbound_message(message, channel, user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc
