"""Aggregated metrics for campaigns and lead bases."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from app.schemas.metrics import MetricsResponse

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
