"""Helpers compartilhados entre testes de integração."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
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


async def create_owner_context(session, *, email_suffix: str | None = None) -> OwnerContext:
    """Factory reutilizável — user + agent + campaign + lead_base + lead."""
    suffix = email_suffix or uuid.uuid4().hex[:8]
    user = User(
        email=f"owner-{suffix}@example.com",
        hashed_password=hash_password("secret"),
        full_name=f"Owner {suffix}",
    )
    session.add(user)
    await session.flush()

    agent = Agent(
        user_id=user.id,
        name=f"Agent_{suffix}",
        mode=AgentMode.ACTIVE,
        status="active",
    )
    session.add(agent)
    await session.flush()

    campaign = Campaign(
        user_id=user.id,
        agent_id=agent.id,
        name=f"Campaign_{suffix}",
        status="active",
    )
    session.add(campaign)
    await session.flush()

    lead_base = LeadBase(
        campaign_id=campaign.id,
        data_recebimento=date.today(),
        source=LeadBaseSource.MANUAL,
    )
    session.add(lead_base)
    await session.flush()

    lead = Lead(
        user_id=user.id,
        lead_base_id=lead_base.id,
        id_cliente=f"CLI-{suffix}",
        nome_cliente=f"Lead {suffix}",
        telefone_1="5511999887766",
    )
    session.add(lead)
    await session.flush()

    return OwnerContext(
        user=user,
        agent=agent,
        campaign=campaign,
        lead_base=lead_base,
        lead=lead,
    )


async def get_admin_user(session):
    from app.core.seed import DEFAULT_ADMIN_EMAIL

    result = await session.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
    return result.scalar_one()
