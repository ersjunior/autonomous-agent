"""
Atendimento inbound compartilhado (R-A.0 + R-A).

Usado por ``inbound_handler`` (mensagem direta) e ``receptive_queue`` (saída da fila).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator.router import route_message
from app.core.activation_defaults import MESSAGING_CHANNELS, normalize_channel_type
from app.models.agent import Agent, AgentMode
from app.models.lead import Lead
from app.services.activation_service import get_agent_channel_settings_row, merged_params
from app.services.capacity_service import (
    ReceptiveCapacityHandle,
    bind_contact_capacity,
    release_contact_capacity,
    release_receptive_handle,
    try_acquire_receptive_capacity,
)
from app.services.human_handoff import enter_human_mode, handle_human_mode_inbound
from app.services.queue_entry_service import (
    record_receptive_answered,
    record_receptive_enqueue,
    record_receptive_immediate_answer,
)
from app.services.receptive_queue import QueuePayload, enqueue_receptive
from app.services.receptive_window import (
    is_receptive_window_open,
    outside_receptive_window_message,
)
from worker.tasks.conversation_routing import agent_routing_metadata
from worker.tasks.lead_tracking import track_inbound_lead_interaction

logger = logging.getLogger(__name__)

QUEUE_WAIT_MESSAGE = (
    "Você está na fila de atendimento. Em breve um de nossos atendentes responderá."
)


async def deliver_channel_text(channel: str, user_id: str, text: str) -> bool:
    """Envio ativo WhatsApp/Telegram (import tardio para evitar ciclo)."""
    from worker.tasks.inbound_handler import _deliver_inbound_response

    return await _deliver_inbound_response(channel, user_id, text)


async def merged_receptive_params(
    session: AsyncSession,
    agent: Agent,
    channel: str,
) -> dict[str, Any]:
    row = await get_agent_channel_settings_row(session, agent.id, channel)
    stored = row.params if row else None
    return merged_params(normalize_channel_type(channel), stored)


async def attend_inbound_message(
    session: AsyncSession,
    *,
    channel: str,
    user_id: str,
    message: str,
    agent: Agent,
    lead: Lead | None,
    capacity: ReceptiveCapacityHandle | None = None,
    bind_capacity: bool = True,
) -> str:
    """
    Roteia pelo grafo, envia resposta e faz tracking.

    Se ``capacity`` for passado e ``bind_capacity``, registra mapeamento para liberação.
    """
    ch = normalize_channel_type(channel)

    handled, wait_msg = handle_human_mode_inbound(ch, user_id)
    if handled:
        if wait_msg:
            await deliver_channel_text(ch, user_id, wait_msg)
        return wait_msg or ""

    agent_context = agent_routing_metadata(agent)
    result = await route_message(
        message,
        ch,
        user_id,
        notify_received=True,
        agent_context=agent_context,
    )
    response_text = result.get("response", "") or ""
    await deliver_channel_text(ch, user_id, response_text)

    escalated = bool(result.get("should_escalate"))
    await track_inbound_lead_interaction(
        session,
        ch,
        user_id,
        message,
        result.get("intent", "other"),
        escalated=escalated,
    )

    if escalated:
        enter_human_mode(ch, user_id)
        release_contact_capacity(ch, user_id)
        if capacity is not None:
            release_receptive_handle(capacity, ch)
    elif capacity and bind_capacity:
        lead_id = str(lead.id) if lead else None
        bind_contact_capacity(
            ch,
            user_id,
            capacity,
            lead_id=lead_id,
        )

    return response_text


async def process_receptive_inbound(
    session: AsyncSession,
    *,
    channel: str,
    user_id: str,
    message: str,
    agent: Agent,
    lead: Lead | None,
    message_sid: str | None = None,
) -> str:
    """
    Fluxo receptivo com fila e capacidade global.

    Fora da janela → mensagem automática, sem fila/slot.
    Sem capacidade → fila + mensagem de espera.
    Com capacidade → atendimento imediato.
    """
    ch = normalize_channel_type(channel)
    if ch not in MESSAGING_CHANNELS:
        return await attend_inbound_message(
            session,
            channel=ch,
            user_id=user_id,
            message=message,
            agent=agent,
            lead=lead,
            bind_capacity=False,
        )

    handled, wait_msg = handle_human_mode_inbound(ch, user_id)
    if handled:
        if wait_msg:
            await deliver_channel_text(ch, user_id, wait_msg)
        return wait_msg or ""

    params = await merged_receptive_params(session, agent, ch)

    if not is_receptive_window_open(params):
        text = outside_receptive_window_message(params)
        await deliver_channel_text(ch, user_id, text)
        logger.info(
            "Receptivo fora da janela channel=%s user=%s (%s–%s)",
            ch,
            user_id,
            params.get("receptivo_horario_inicio"),
            params.get("receptivo_horario_fim"),
        )
        return text

    capacity = try_acquire_receptive_capacity(str(agent.id), ch, params)
    if capacity is None:
        enqueue_receptive(
            ch,
            user_id,
            message=message,
            agent_id=str(agent.id),
            message_sid=message_sid,
        )
        await record_receptive_enqueue(
            session,
            channel_type=ch,
            user_id=user_id,
            agent_id=agent.id,
            lead_id=lead.id if lead else None,
        )
        await deliver_channel_text(ch, user_id, QUEUE_WAIT_MESSAGE)
        logger.info(
            "Receptivo enfileirado channel=%s user=%s agent=%s",
            ch,
            user_id,
            agent.name,
        )
        return QUEUE_WAIT_MESSAGE

    logger.info(
        "Receptivo atendimento imediato channel=%s user=%s agent=%s capacity_weight=%s",
        ch,
        user_id,
        agent.name,
        capacity.weight,
    )
    await record_receptive_immediate_answer(
        session,
        channel_type=ch,
        user_id=user_id,
        agent_id=agent.id,
        lead_id=lead.id if lead else None,
    )
    return await attend_inbound_message(
        session,
        channel=ch,
        user_id=user_id,
        message=message,
        agent=agent,
        lead=lead,
        capacity=capacity,
        bind_capacity=True,
    )


async def attend_from_queue_payload(
    session: AsyncSession,
    payload: QueuePayload,
    capacity: ReceptiveCapacityHandle,
) -> str:
    """Atende um item dequeue da fila (agent_id no payload)."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.agent import Agent

    handled, wait_msg = handle_human_mode_inbound(payload.channel, payload.user_id)
    if handled:
        if wait_msg:
            await deliver_channel_text(payload.channel, payload.user_id, wait_msg)
        release_receptive_handle(capacity, payload.channel)
        return wait_msg or ""

    enqueued_dt = datetime.fromtimestamp(payload.enqueued_at, tz=timezone.utc)
    await record_receptive_answered(
        session,
        channel_type=payload.channel,
        user_id=payload.user_id,
        agent_id=payload.agent_id,
        enqueued_at=enqueued_dt,
    )

    agent_uuid = uuid.UUID(payload.agent_id)
    result = await session.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise RuntimeError(f"Agente da fila não encontrado: {payload.agent_id}")

    lead = None
    from worker.tasks.lead_tracking import find_lead_by_channel_user

    lead = await find_lead_by_channel_user(session, payload.channel, payload.user_id)

    return await attend_inbound_message(
        session,
        channel=payload.channel,
        user_id=payload.user_id,
        message=payload.message,
        agent=agent,
        lead=lead,
        capacity=capacity,
        bind_capacity=True,
    )


def should_apply_receptive_queue(agent: Agent) -> bool:
    return agent.mode == AgentMode.RECEPTIVE
