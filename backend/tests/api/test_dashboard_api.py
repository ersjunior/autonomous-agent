"""Camada 3 — dashboard summary API."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.lead_interaction import LeadInteraction

pytestmark = pytest.mark.api

DASHBOARD = "/api/v1/dashboard"


async def test_dashboard_summary_requires_auth(client) -> None:
    response = await client.get(f"{DASHBOARD}/summary")
    assert response.status_code == 401


async def test_dashboard_summary_returns_200_with_schema(
    auth_client,
    owner_ctx,
    db_session,
    system_seeds,
) -> None:
    db_session.add(
        LeadInteraction(
            lead_id=owner_ctx.lead.id,
            campaign_id=owner_ctx.campaign.id,
            channel_type="whatsapp",
            status="em_andamento",
            tentativas=1,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    response = await auth_client.get(f"{DASHBOARD}/summary")
    assert response.status_code == 200
    body = response.json()
    assert "cards" in body
    assert set(body["cards"]) == {
        "agents",
        "active_channels",
        "leads",
        "active_campaigns",
    }
    assert "leads_acionados" in body
    assert "leads_virgens" in body
    assert body["tentativas_por_canal"]["whatsapp"] >= 1
    assert body["tentativas_por_status"]["em_andamento"] >= 1


async def test_dashboard_summary_invalid_channel_returns_400(auth_client) -> None:
    response = await auth_client.get(
        f"{DASHBOARD}/summary",
        params={"channel_type": "invalid"},
    )
    assert response.status_code == 400


async def test_dashboard_summary_channel_filter(auth_client, owner_ctx, db_session) -> None:
    db_session.add(
        LeadInteraction(
            lead_id=owner_ctx.lead.id,
            campaign_id=owner_ctx.campaign.id,
            channel_type="voice",
            status="acionado",
            tentativas=4,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    response = await auth_client.get(
        f"{DASHBOARD}/summary",
        params={"channel_type": "voice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tentativas_por_canal"] == {"voice": 4}
    assert body["tentativas_por_status"]["acionado"] == 1


async def test_dashboard_campaigns_requires_auth(client) -> None:
    response = await client.get(f"{DASHBOARD}/campaigns")
    assert response.status_code == 401


async def test_dashboard_campaigns_returns_200_with_schema(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    db_session.add(
        LeadInteraction(
            lead_id=owner_ctx.lead.id,
            campaign_id=owner_ctx.campaign.id,
            channel_type="whatsapp",
            status="em_andamento",
            tentativas=2,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    response = await auth_client.get(f"{DASHBOARD}/campaigns")
    assert response.status_code == 200
    body = response.json()
    assert "campaigns" in body
    assert isinstance(body["campaigns"], list)
    assert len(body["campaigns"]) >= 1
    row = next(r for r in body["campaigns"] if r["campaign_id"] == str(owner_ctx.campaign.id))
    assert row["campaign_name"] == owner_ctx.campaign.name
    assert row["tentativas"] >= 2
    assert "spin" in row
    assert "conversao" in row


async def test_dashboard_campaigns_invalid_channel_returns_400(auth_client) -> None:
    response = await auth_client.get(
        f"{DASHBOARD}/campaigns",
        params={"channel_type": "invalid"},
    )
    assert response.status_code == 400
