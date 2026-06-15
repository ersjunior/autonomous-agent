"""Integration tests — dashboard summary service."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.tabulacao import Tabulacao
from app.services.dashboard_metrics import get_dashboard_campaigns, get_dashboard_summary
from tests.integration.helpers import create_owner_context

pytestmark = pytest.mark.integration


async def test_dashboard_summary_counts_acionados_virgens_and_aggregates(
    db_session,
    system_seeds,
) -> None:
    """Service: leads acionados/virgens, SUM(tentativas) e COUNT por status."""
    ctx = await create_owner_context(db_session)

    virgin_lead = Lead(
        user_id=ctx.user.id,
        lead_base_id=ctx.lead_base.id,
        nome_cliente="Virgin Lead",
        telefone_1="5511888777666",
    )
    db_session.add(virgin_lead)
    await db_session.flush()

    from app.models.lead_interaction import LeadInteraction

    db_session.add(
        LeadInteraction(
            lead_id=ctx.lead.id,
            campaign_id=ctx.campaign.id,
            channel_type="whatsapp",
            status="em_andamento",
            tentativas=2,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        LeadInteraction(
            lead_id=ctx.lead.id,
            campaign_id=ctx.campaign.id,
            channel_type="voice",
            status="convertido",
            tentativas=1,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    summary = await get_dashboard_summary(db_session, user_id=ctx.user.id)

    assert summary.leads_acionados == 1
    assert summary.leads_virgens == 1
    assert summary.tentativas_por_canal["whatsapp"] == 2
    assert summary.tentativas_por_canal["voice"] == 1
    assert summary.tentativas_por_canal["telegram"] == 0
    assert summary.tentativas_por_status["em_andamento"] == 1
    assert summary.tentativas_por_status["convertido"] == 1
    assert summary.cards.active_campaigns >= 1


async def test_dashboard_summary_channel_filter(db_session, system_seeds) -> None:
    ctx = await create_owner_context(db_session)

    from app.models.lead_interaction import LeadInteraction

    db_session.add(
        LeadInteraction(
            lead_id=ctx.lead.id,
            campaign_id=ctx.campaign.id,
            channel_type="whatsapp",
            status="em_andamento",
            tentativas=3,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        LeadInteraction(
            lead_id=ctx.lead.id,
            campaign_id=ctx.campaign.id,
            channel_type="voice",
            status="acionado",
            tentativas=5,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    summary = await get_dashboard_summary(
        db_session,
        user_id=ctx.user.id,
        channel_type="voice",
    )

    assert summary.leads_acionados == 1
    assert summary.tentativas_por_canal == {"voice": 5}
    assert summary.tentativas_por_status["acionado"] == 1
    assert summary.tentativas_por_status["em_andamento"] == 0


async def test_dashboard_campaigns_distinct_lead_metrics_and_spin(
    db_session,
    system_seeds,
) -> None:
    """Contato/CPC/Sucesso contam lead único; spin = tentativas/leads."""
    ctx = await create_owner_context(db_session)

    second_lead = Lead(
        user_id=ctx.user.id,
        lead_base_id=ctx.lead_base.id,
        nome_cliente="Second Lead",
        telefone_1="5511777666555",
    )
    db_session.add(second_lead)
    await db_session.flush()

    from app.models.lead_interaction import LeadInteraction

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            LeadInteraction(
                lead_id=ctx.lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="whatsapp",
                status="em_andamento",
                tentativas=4,
                data_acionamento=now,
                data_ultimo_contato=now,
            ),
            LeadInteraction(
                lead_id=ctx.lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="telegram",
                status="convertido",
                tentativas=2,
                data_acionamento=now,
            ),
            LeadInteraction(
                lead_id=second_lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="whatsapp",
                status="recusou",
                tentativas=6,
                data_acionamento=now,
            ),
        ]
    )
    await db_session.flush()

    result = await get_dashboard_campaigns(db_session, user_id=ctx.user.id)
    row = next(r for r in result.campaigns if r.campaign_id == ctx.campaign.id)

    assert row.leads == 2
    assert row.tentativas == 12
    assert row.spin == 6.0
    assert row.contato == 2
    assert row.cpc == 2
    assert row.sucesso == 1
    assert row.conversao == 0.5


async def test_dashboard_campaigns_cpc_includes_escalado_tabulacao(
    db_session,
    system_seeds,
) -> None:
    ctx = await create_owner_context(db_session)
    escalado_id = (
        await db_session.execute(
            select(Tabulacao.id).where(
                Tabulacao.is_system.is_(True),
                Tabulacao.codigo == "NEG:ESCALADO",
            )
        )
    ).scalar_one()

    from app.models.lead_interaction import LeadInteraction

    now = datetime.now(timezone.utc)
    db_session.add(
        LeadInteraction(
            lead_id=ctx.lead.id,
            campaign_id=ctx.campaign.id,
            channel_type="whatsapp",
            status="em_andamento",
            tentativas=1,
            data_acionamento=now,
            tabulacao_id=escalado_id,
        )
    )
    await db_session.flush()

    row = next(
        r
        for r in (
            await get_dashboard_campaigns(db_session, user_id=ctx.user.id)
        ).campaigns
        if r.campaign_id == ctx.campaign.id
    )
    assert row.cpc == 1
    assert row.sucesso == 0
    assert row.conversao == 0.0


async def test_dashboard_campaigns_empty_campaign_has_zeros(
    db_session,
    system_seeds,
) -> None:
    ctx = await create_owner_context(db_session)
    empty = Campaign(
        user_id=ctx.user.id,
        agent_id=ctx.agent.id,
        name="Empty Campaign",
        status="draft",
    )
    db_session.add(empty)
    await db_session.flush()

    row = next(
        r
        for r in (
            await get_dashboard_campaigns(db_session, user_id=ctx.user.id)
        ).campaigns
        if r.campaign_id == empty.id
    )
    assert row.leads == 0
    assert row.tentativas == 0
    assert row.spin == 0.0
    assert row.contato == 0
    assert row.cpc == 0
    assert row.sucesso == 0
    assert row.conversao == 0.0
    assert row.data_recebimento is None


async def test_dashboard_campaigns_channel_filter(db_session, system_seeds) -> None:
    ctx = await create_owner_context(db_session)

    from app.models.lead_interaction import LeadInteraction

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            LeadInteraction(
                lead_id=ctx.lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="whatsapp",
                status="em_andamento",
                tentativas=10,
                data_acionamento=now,
                data_ultimo_contato=now,
            ),
            LeadInteraction(
                lead_id=ctx.lead.id,
                campaign_id=ctx.campaign.id,
                channel_type="voice",
                status="convertido",
                tentativas=3,
                data_acionamento=now,
            ),
        ]
    )
    await db_session.flush()

    row = next(
        r
        for r in (
            await get_dashboard_campaigns(
                db_session,
                user_id=ctx.user.id,
                channel_type="voice",
            )
        ).campaigns
        if r.campaign_id == ctx.campaign.id
    )
    assert row.tentativas == 3
    assert row.contato == 1
    assert row.sucesso == 1
    assert row.cpc == 1
    assert row.conversao == 1.0
