"""Resolução de tenant (dono do workspace) — regra compartilhada com handoff/KB."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.lead import Lead


async def resolve_tenant_user_id(
    session: AsyncSession,
    agent: Agent,
    *,
    lead: Lead | None = None,
    campaign: Campaign | None = None,
) -> uuid.UUID:
    """
    Dono do tenant para identidade de workspace, KB e handoff.

    Precedência: ``campaign.user_id`` → ``lead.lead_base.campaign.user_id`` →
    ``lead.user_id`` → ``agent.user_id``.
    """
    if campaign is not None:
        return campaign.user_id

    if lead is not None:
        if lead.lead_base is not None and lead.lead_base.campaign_id is not None:
            camp = await session.get(Campaign, lead.lead_base.campaign_id)
            if camp is not None:
                return camp.user_id
        return lead.user_id

    return agent.user_id
