"""Camada 3 — métricas por agente API."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.lead_interaction import LeadInteraction

pytestmark = pytest.mark.api

METRICS = "/api/v1/metrics"


async def test_metrics_by_agent_requires_auth(client) -> None:
    response = await client.get(f"{METRICS}/by-agent")
    assert response.status_code == 401


async def test_metrics_by_agent_returns_200_with_schema(
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
            status="convertido",
            tentativas=1,
            data_acionamento=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    response = await auth_client.get(f"{METRICS}/by-agent")
    assert response.status_code == 200
    body = response.json()
    assert "agents" in body
    assert isinstance(body["agents"], list)
    assert len(body["agents"]) >= 1

    row = next(r for r in body["agents"] if r["agent_id"] == str(owner_ctx.agent.id))
    assert row["agent_name"] == owner_ctx.agent.name
    assert row["mode"] == "ACTIVE"
    assert row["total_acionamentos"] >= 1
    assert row["por_status"]["convertido"] >= 1
    assert "taxa_conversao" in row
    assert "taxa_resposta" in row
