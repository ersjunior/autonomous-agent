"""Helpers compartilhados entre testes de integração."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.interaction import Interaction
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


async def create_lead_interaction(
    session,
    *,
    lead_id: uuid.UUID,
    campaign_id: uuid.UUID,
    channel_type: str = "whatsapp",
    status: str = "em_andamento",
    data_acionamento: datetime | None = None,
    data_ultimo_contato: datetime | None = None,
    tentativas: int = 1,
) -> LeadInteraction:
    li = LeadInteraction(
        lead_id=lead_id,
        campaign_id=campaign_id,
        channel_type=channel_type.lower(),
        status=status,
        tentativas=tentativas,
        data_acionamento=data_acionamento,
        data_ultimo_contato=data_ultimo_contato,
    )
    session.add(li)
    await session.flush()
    return li


async def create_lead_on_base(
    session,
    owner_ctx: OwnerContext,
    *,
    suffix: str,
    telefone: str,
) -> Lead:
    lead = Lead(
        user_id=owner_ctx.user.id,
        lead_base_id=owner_ctx.lead_base.id,
        id_cliente=f"CLI-{suffix}",
        nome_cliente=f"Lead {suffix}",
        telefone_1=telefone,
    )
    session.add(lead)
    await session.flush()
    return lead


async def create_activation_records(
    session,
    owner_ctx: OwnerContext,
    count: int,
    *,
    base_time: datetime | None = None,
    channel_type: str = "whatsapp",
    status: str = "em_andamento",
) -> list[LeadInteraction]:
    """Cria N LIs com data_acionamento distinta (mais recente = índice maior)."""
    base = base_time or datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
    records: list[LeadInteraction] = []
    for i in range(count):
        suffix = f"{i:02d}-{uuid.uuid4().hex[:4]}"
        lead = await create_lead_on_base(
            session,
            owner_ctx,
            suffix=suffix,
            telefone=f"5511999887{i:03d}",
        )
        li = await create_lead_interaction(
            session,
            lead_id=lead.id,
            campaign_id=owner_ctx.campaign.id,
            channel_type=channel_type,
            status=status,
            data_acionamento=base + timedelta(hours=i),
        )
        records.append(li)
    return records


async def create_interaction_record(
    session,
    *,
    user_id: str,
    message: str = "Mensagem do cliente",
    response: str = "Resposta do agente",
    intent: str = "question",
    created_at: datetime | None = None,
) -> Interaction:
    """Insere Interaction com embedding dummy (histórico não usa similaridade)."""
    dims = settings.embedding_dimensions
    row = Interaction(
        user_id=user_id,
        message=message,
        response=response,
        intent=intent,
        embedding=[0.0] * dims,
    )
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    await session.flush()
    return row
