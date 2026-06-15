"""Integration tests — métricas agregadas por agente."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.agent import Agent, AgentMode
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.services.metrics import get_metrics_by_agent
from tests.integration.helpers import create_owner_context

pytestmark = pytest.mark.integration


async def test_metrics_by_agent_aggregates_via_campaign_agent_id(
    db_session,
    system_seeds,
) -> None:
    """Interações somam no agente da campanha (campaign.agent_id)."""
    ctx = await create_owner_context(db_session)

    second_lead = Lead(
        user_id=ctx.user.id,
        lead_base_id=ctx.lead_base.id,
        nome_cliente="Second Lead",
        telefone_1="5511777666555",
    )
    db_session.add(second_lead)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            LeadInteraction(
                lead_id=ctx.lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="whatsapp",
                status="em_andamento",
                tentativas=1,
                data_acionamento=now,
            ),
            LeadInteraction(
                lead_id=ctx.lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="telegram",
                status="convertido",
                tentativas=1,
                data_acionamento=now,
            ),
            LeadInteraction(
                lead_id=second_lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="whatsapp",
                status="recusou",
                tentativas=1,
                data_acionamento=now,
            ),
        ]
    )
    await db_session.flush()

    result = await get_metrics_by_agent(db_session, user_id=ctx.user.id)
    row = next(r for r in result.agents if r.agent_id == ctx.agent.id)

    assert row.agent_name == ctx.agent.name
    assert row.mode == "ACTIVE"
    assert row.total_leads == 2
    assert row.total_acionamentos == 3
    assert row.por_status["em_andamento"] == 1
    assert row.por_status["convertido"] == 1
    assert row.por_status["recusou"] == 1
    assert row.por_canal["whatsapp"] == 2
    assert row.por_canal["telegram"] == 1
    assert row.taxa_conversao == pytest.approx(1 / 3)
    assert row.taxa_resposta == pytest.approx(1.0)


async def test_metrics_by_agent_includes_agent_without_campaign_with_zeros(
    db_session,
    system_seeds,
) -> None:
    ctx = await create_owner_context(db_session)

    orphan = Agent(
        user_id=ctx.user.id,
        name="Agente_Sem_Campanha",
        mode=AgentMode.RECEPTIVE,
        status="active",
    )
    db_session.add(orphan)
    await db_session.flush()

    result = await get_metrics_by_agent(db_session, user_id=ctx.user.id)
    row = next(r for r in result.agents if r.agent_id == orphan.id)

    assert row.total_leads == 0
    assert row.total_acionamentos == 0
    assert row.taxa_conversao == 0.0
    assert row.taxa_resposta == 0.0
    assert sum(row.por_status.values()) == 0
    assert sum(row.por_canal.values()) == 0
