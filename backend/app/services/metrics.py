"""Aggregated metrics for campaigns and lead bases."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from app.schemas.metrics import AgentMetricsResponse, AgentMetricsRow, MetricsResponse

STATUS_KEYS = (
    "pendente",
    "acionado",
    "em_andamento",
    "nao_atendido",
    "convertido",
    "recusou",
    "erro",
)

CHANNEL_KEYS = ("whatsapp", "telegram", "voice")


def _empty_status_counts() -> dict[str, int]:
    return {key: 0 for key in STATUS_KEYS}


def _empty_channel_counts() -> dict[str, int]:
    return {key: 0 for key in CHANNEL_KEYS}


def _build_metrics_response(
    *,
    total_leads: int,
    total_acionamentos: int,
    status_rows: list[tuple[str, int]],
    channel_rows: list[tuple[str, int]],
) -> MetricsResponse:
    por_status = _empty_status_counts()
    for status, count in status_rows:
        por_status[status] = int(count)

    por_canal = _empty_channel_counts()
    for channel, count in channel_rows:
        channel_key = channel.lower()
        if channel_key in por_canal:
            por_canal[channel_key] = int(count)

    convertido = por_status["convertido"]
    responded = por_status["em_andamento"] + convertido + por_status["recusou"]
    total = total_acionamentos

    return MetricsResponse(
        total_leads=total_leads,
        total_acionamentos=total_acionamentos,
        por_status=por_status,
        por_canal=por_canal,
        taxa_conversao=(convertido / total) if total else 0.0,
        taxa_resposta=(responded / total) if total else 0.0,
    )


async def get_campaign_metrics(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> MetricsResponse:
    total_leads = await db.scalar(
        select(func.count(Lead.id))
        .select_from(Lead)
        .join(LeadBase, Lead.lead_base_id == LeadBase.id)
        .where(LeadBase.campaign_id == campaign_id)
    )

    total_acionamentos = await db.scalar(
        select(func.count(LeadInteraction.id)).where(
            LeadInteraction.campaign_id == campaign_id
        )
    )

    status_result = await db.execute(
        select(LeadInteraction.status, func.count())
        .where(LeadInteraction.campaign_id == campaign_id)
        .group_by(LeadInteraction.status)
    )

    channel_result = await db.execute(
        select(LeadInteraction.channel_type, func.count())
        .where(LeadInteraction.campaign_id == campaign_id)
        .group_by(LeadInteraction.channel_type)
    )

    return _build_metrics_response(
        total_leads=total_leads or 0,
        total_acionamentos=total_acionamentos or 0,
        status_rows=list(status_result.all()),
        channel_rows=list(channel_result.all()),
    )


async def get_lead_base_metrics(
    db: AsyncSession,
    lead_base_id: uuid.UUID,
) -> MetricsResponse:
    total_leads = await db.scalar(
        select(func.count(Lead.id)).where(Lead.lead_base_id == lead_base_id)
    )

    total_acionamentos = await db.scalar(
        select(func.count(LeadInteraction.id))
        .select_from(LeadInteraction)
        .join(Lead, LeadInteraction.lead_id == Lead.id)
        .where(Lead.lead_base_id == lead_base_id)
    )

    status_result = await db.execute(
        select(LeadInteraction.status, func.count())
        .select_from(LeadInteraction)
        .join(Lead, LeadInteraction.lead_id == Lead.id)
        .where(Lead.lead_base_id == lead_base_id)
        .group_by(LeadInteraction.status)
    )

    channel_result = await db.execute(
        select(LeadInteraction.channel_type, func.count())
        .select_from(LeadInteraction)
        .join(Lead, LeadInteraction.lead_id == Lead.id)
        .where(Lead.lead_base_id == lead_base_id)
        .group_by(LeadInteraction.channel_type)
    )

    return _build_metrics_response(
        total_leads=total_leads or 0,
        total_acionamentos=total_acionamentos or 0,
        status_rows=list(status_result.all()),
        channel_rows=list(channel_result.all()),
    )


def _agent_scope(user_id: uuid.UUID):
    """Agentes visíveis ao usuário (dono ou seed is_system)."""
    return or_(Agent.is_system.is_(True), Agent.user_id == user_id)


def _campaign_scope(user_id: uuid.UUID):
    """Campanhas visíveis ao usuário (dono ou seed is_system)."""
    return or_(Campaign.is_system.is_(True), Campaign.user_id == user_id)


async def get_metrics_by_agent(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> AgentMetricsResponse:
    """
    Métricas simples agregadas por agente (uma linha por agente visível).

    Estratégia (sem N+1): Q1 lista agentes; Q2–Q5 agregam por ``Campaign.agent_id``
    com JOIN em campanhas no escopo do usuário; merge em Python por agent_id.

    LIMITAÇÃO: a interação é atribuída ao ``Campaign.agent_id`` da campanha gravada
    no lead_interaction — mesma semântica de ``get_campaign_metrics``, não o agente
    efetivo do roteamento em fallbacks para seeds do sistema.
    """
    agent_scope = _agent_scope(user_id)
    campaign_scope = _campaign_scope(user_id)

    agent_rows = list(
        (
            await db.execute(
                select(Agent.id, Agent.name, Agent.mode)
                .where(agent_scope)
                .order_by(Agent.mode, Agent.name)
            )
        ).all()
    )

    if not agent_rows:
        return AgentMetricsResponse(agents=[])

    rows_by_id: dict[uuid.UUID, dict] = {
        agent_id: {
            "agent_name": name,
            "mode": mode.value if hasattr(mode, "value") else str(mode),
            "total_leads": 0,
            "total_acionamentos": 0,
        }
        for agent_id, name, mode in agent_rows
    }

    lead_stats = await db.execute(
        select(Campaign.agent_id, func.count(func.distinct(Lead.id)))
        .select_from(Lead)
        .join(LeadBase, Lead.lead_base_id == LeadBase.id)
        .join(Campaign, LeadBase.campaign_id == Campaign.id)
        .where(campaign_scope)
        .group_by(Campaign.agent_id)
    )
    for agent_id, lead_count in lead_stats.all():
        bucket = rows_by_id.get(agent_id)
        if bucket is None:
            continue
        bucket["total_leads"] = int(lead_count or 0)

    acionamento_stats = await db.execute(
        select(Campaign.agent_id, func.count(LeadInteraction.id))
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(campaign_scope)
        .group_by(Campaign.agent_id)
    )
    for agent_id, total in acionamento_stats.all():
        bucket = rows_by_id.get(agent_id)
        if bucket is None:
            continue
        bucket["total_acionamentos"] = int(total or 0)

    status_stats = await db.execute(
        select(Campaign.agent_id, LeadInteraction.status, func.count())
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(campaign_scope)
        .group_by(Campaign.agent_id, LeadInteraction.status)
    )
    status_by_agent: dict[uuid.UUID, list[tuple[str, int]]] = {}
    for agent_id, status, count in status_stats.all():
        status_by_agent.setdefault(agent_id, []).append((status, int(count)))

    channel_stats = await db.execute(
        select(Campaign.agent_id, LeadInteraction.channel_type, func.count())
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(campaign_scope)
        .group_by(Campaign.agent_id, LeadInteraction.channel_type)
    )
    channel_by_agent: dict[uuid.UUID, list[tuple[str, int]]] = {}
    for agent_id, channel, count in channel_stats.all():
        channel_by_agent.setdefault(agent_id, []).append((channel, int(count)))

    agents_out: list[AgentMetricsRow] = []
    for agent_id, name, mode in agent_rows:
        data = rows_by_id[agent_id]
        metrics = _build_metrics_response(
            total_leads=data["total_leads"],
            total_acionamentos=data["total_acionamentos"],
            status_rows=status_by_agent.get(agent_id, []),
            channel_rows=channel_by_agent.get(agent_id, []),
        )
        agents_out.append(
            AgentMetricsRow(
                agent_id=agent_id,
                agent_name=data["agent_name"],
                mode=data["mode"],
                total_leads=metrics.total_leads,
                total_acionamentos=metrics.total_acionamentos,
                por_status=metrics.por_status,
                por_canal=metrics.por_canal,
                taxa_conversao=metrics.taxa_conversao,
                taxa_resposta=metrics.taxa_resposta,
            )
        )

    return AgentMetricsResponse(agents=agents_out)
