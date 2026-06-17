"""Enriquecimento do AgentState context antes do grafo (identidade híbrida)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.identity import resolve_identity_config
from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.tenant_resolution import resolve_tenant_user_id
from app.services.user_identity import load_user_identity


async def enrich_agent_context_with_identity(
    session: AsyncSession,
    agent_context: dict[str, Any],
    agent: Agent,
    *,
    lead: Lead | None = None,
    campaign: Campaign | None = None,
) -> dict[str, Any]:
    """
    Mescla identidade workspace + agente em ``agent_config`` (sem I/O no prompt builder).

    Também alinha ``owner_user_id`` ao tenant resolvido (KB/handoff).
    """
    enriched = dict(agent_context)
    tenant_id = await resolve_tenant_user_id(
        session,
        agent,
        lead=lead,
        campaign=campaign,
    )
    workspace_identity = await load_user_identity(session, tenant_id)
    base_config = dict(enriched.get("agent_config") or {})
    enriched["agent_config"] = resolve_identity_config(workspace_identity, base_config)
    enriched["owner_user_id"] = str(tenant_id)
    if lead is not None:
        enriched["lead_id"] = str(lead.id)
        enriched["lead_name"] = (lead.nome_cliente or "").strip() or None
    return enriched
