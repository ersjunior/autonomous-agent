"""Conversation lifecycle and inbound agent routing (ACTIVE vs RECEPTIVE)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction

logger = logging.getLogger(__name__)

# Statuses that close the active outbound-owned conversation (project convention).
TERMINAL_STATUSES = frozenset({"convertido", "recusou", "nao_atendido", "erro"})

SEED_AGENT_ACTIVE_NAME = "Agente_Ativo"
SEED_AGENT_RECEPTIVE_NAME = "Agente_Receptivo"

_default_agents_cache: dict[str, Agent | None] = {"ACTIVE": None, "RECEPTIVE": None}


def is_active_conversation_open(
    lead_interaction: LeadInteraction | None,
    timeout_hours: int | None = None,
) -> bool:
    """
    Active conversation is OPEN only when ALL hold:
      - record exists
      - data_acionamento is set (outbound touch happened)
      - status is not terminal
      - last contact within timeout_hours (inactivity window)

    Uses active_conversation_timeout_hours (default 24h), separate from
    status_timeout_hours which drives the Celery sweep to nao_atendido (48h default).
    """
    if lead_interaction is None:
        return False
    if lead_interaction.data_acionamento is None:
        return False
    if (lead_interaction.status or "").lower() in TERMINAL_STATUSES:
        return False

    hours = timeout_hours if timeout_hours is not None else settings.active_conversation_timeout_hours
    last = lead_interaction.data_ultimo_contato or lead_interaction.data_acionamento
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return last >= cutoff


async def _get_system_agent_by_mode(session: AsyncSession, mode: AgentMode) -> Agent:
    """Fallback seed agents (is_system + mode); cached per worker process."""
    cache_key = mode.value
    cached = _default_agents_cache.get(cache_key)
    if cached is not None:
        return cached

    name = SEED_AGENT_ACTIVE_NAME if mode == AgentMode.ACTIVE else SEED_AGENT_RECEPTIVE_NAME
    result = await session.execute(
        select(Agent).where(
            Agent.is_system.is_(True),
            Agent.mode == mode,
            Agent.name == name,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise RuntimeError(
            f"Agente padrão do sistema não encontrado: name={name!r} mode={mode.value}"
        )
    _default_agents_cache[cache_key] = agent
    return agent


async def get_latest_lead_interaction(
    session: AsyncSession,
    lead_id: uuid.UUID,
    channel_type: str,
) -> LeadInteraction | None:
    """
    Most recent LeadInteraction for this lead on the given channel (normalized lowercase).
    Ordered by data_ultimo_contato desc, then created_at desc.
    """
    channel = channel_type.lower()
    result = await session.execute(
        select(LeadInteraction)
        .options(
            selectinload(LeadInteraction.campaign).selectinload(Campaign.agent),
        )
        .where(
            LeadInteraction.lead_id == lead_id,
            LeadInteraction.channel_type == channel,
        )
        .order_by(
            LeadInteraction.data_ultimo_contato.desc().nulls_last(),
            LeadInteraction.created_at.desc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def agent_personality_context(agent: Agent) -> str:
    """Text block injected into the LLM system prompt for the selected agent."""
    parts = [f"Agente: {agent.name} (modo {agent.mode.value})"]
    if agent.description:
        parts.append(agent.description.strip())
    if agent.config:
        parts.append(f"Configuração: {agent.config}")
    return "\n".join(parts)


def agent_routing_metadata(agent: Agent) -> dict[str, Any]:
    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "agent_mode": agent.mode.value,
        "agent_personality": agent_personality_context(agent),
    }


async def resolve_inbound_agent(
    session: AsyncSession,
    lead: Lead | None,
    channel_type: str,
) -> Agent:
    """
    Inbound routing:
      - Unknown contact (no lead) → Agente_Receptivo (RECEPTIVE) seed.
      - Open active conversation (outbound acionamento + not terminal + not expired)
        → campaign ACTIVE agent if mode matches, else Agente_Ativo seed.
      - First contact or closed conversation → campaign RECEPTIVE agent if applicable,
        else Agente_Receptivo seed.

    Interaction scope: latest record per (lead_id, channel_type).
    """
    channel = channel_type.lower()

    if lead is None:
        agent = await _get_system_agent_by_mode(session, AgentMode.RECEPTIVE)
        logger.info(
            "Inbound routing: unknown contact channel=%s → %s (%s)",
            channel,
            agent.name,
            agent.mode.value,
        )
        return agent

    interaction = await get_latest_lead_interaction(session, lead.id, channel)

    if is_active_conversation_open(interaction):
        campaign_agent = (
            interaction.campaign.agent
            if interaction and interaction.campaign
            else None
        )
        if campaign_agent is not None and campaign_agent.mode == AgentMode.ACTIVE:
            agent = campaign_agent
        else:
            agent = await _get_system_agent_by_mode(session, AgentMode.ACTIVE)
        logger.info(
            "Inbound routing: open active conversation lead=%s channel=%s → %s (%s)",
            lead.id,
            channel,
            agent.name,
            agent.mode.value,
        )
        return agent

    campaign_agent = (
        interaction.campaign.agent
        if interaction and interaction.campaign
        else None
    )
    if campaign_agent is not None and campaign_agent.mode == AgentMode.RECEPTIVE:
        agent = campaign_agent
    else:
        agent = await _get_system_agent_by_mode(session, AgentMode.RECEPTIVE)
    logger.info(
        "Inbound routing: closed/new conversation lead=%s channel=%s status=%s → %s (%s)",
        lead.id,
        channel,
        interaction.status if interaction else "none",
        agent.name,
        agent.mode.value,
    )
    return agent
