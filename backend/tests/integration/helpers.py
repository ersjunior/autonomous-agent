"""Helpers compartilhados entre testes de integração."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.models.user import User


@dataclass
class OwnerContext:
    user: User
    agent: Agent
    campaign: Campaign
    lead_base: LeadBase
    lead: Lead


async def tabulacao_codigo_for(session, lead_interaction: LeadInteraction) -> str | None:
    await session.refresh(lead_interaction, attribute_names=["tabulacao_id"])
    if lead_interaction.tabulacao_id is None:
        return None
    tab = await session.get(Tabulacao, lead_interaction.tabulacao_id)
    return tab.codigo if tab else None
