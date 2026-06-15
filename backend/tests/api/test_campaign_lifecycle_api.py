"""Camada 3 — lifecycle HTTP de campanhas (start/stop) com mock Celery."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.authorization import SYSTEM_RECORD_DELETE_DETAIL
from app.models.agent_activation import AgentActivation
from app.models.campaign import Campaign, CampaignChannel
from tests.api.ownership_helpers import foreign_campaign_id
from tests.integration.helpers import add_campaign_channel, add_lead_base_channel

pytestmark = pytest.mark.api

BASE = "/api/v1/campaigns/"


@pytest.fixture
def mock_send_campaign_message(monkeypatch):
    """Evita enfileirar Celery real; registra chamadas a send_campaign_message.delay."""
    state: dict = {"calls": []}

    def fake_delay(lead_id: str, campaign_id: str) -> None:
        state["calls"].append((lead_id, campaign_id))

    monkeypatch.setattr(
        "app.api.v1.campaigns.send_campaign_message.delay",
        fake_delay,
    )
    return state


async def _prepare_runnable_campaign(db_session, owner_ctx) -> None:
    """Canais na campanha + canal na base do lead; status draft para start."""
    await add_campaign_channel(db_session, owner_ctx.campaign.id, "whatsapp")
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    owner_ctx.campaign.status = "draft"
    await db_session.flush()


async def _activation_states(db_session, campaign_id: uuid.UUID) -> list[bool]:
    result = await db_session.execute(
        select(AgentActivation.is_running).where(
            AgentActivation.campaign_id == campaign_id
        )
    )
    return list(result.scalars().all())


async def test_campaign_start_from_draft_returns_200_and_enqueues(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    await _prepare_runnable_campaign(db_session, owner_ctx)
    campaign_id = owner_ctx.campaign.id

    response = await auth_client.post(f"{BASE}{campaign_id}/start")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "started"
    assert body["leads_dispatched"] == 1
    assert len(mock_send_campaign_message["calls"]) == 1
    assert mock_send_campaign_message["calls"][0][1] == str(campaign_id)

    await db_session.refresh(owner_ctx.campaign)
    assert owner_ctx.campaign.status == "active"
    assert all(await _activation_states(db_session, campaign_id))


async def test_campaign_start_from_active_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    await _prepare_runnable_campaign(db_session, owner_ctx)
    owner_ctx.campaign.status = "active"
    await db_session.flush()

    response = await auth_client.post(f"{BASE}{owner_ctx.campaign.id}/start")
    assert response.status_code == 400
    assert "cannot be started" in response.json()["detail"]
    assert mock_send_campaign_message["calls"] == []


async def test_campaign_start_without_channels_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    bare = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="Sem canais",
        status="draft",
    )
    db_session.add(bare)
    await db_session.flush()

    response = await auth_client.post(f"{BASE}{bare.id}/start")
    assert response.status_code == 400
    assert response.json()["detail"] == "Campaign has no channels configured"
    assert mock_send_campaign_message["calls"] == []


async def test_campaign_stop_from_active_returns_200(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    await _prepare_runnable_campaign(db_session, owner_ctx)
    campaign_id = owner_ctx.campaign.id

    start = await auth_client.post(f"{BASE}{campaign_id}/start")
    assert start.status_code == 200

    response = await auth_client.post(f"{BASE}{campaign_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "paused"
    assert body["activations_stopped"] >= 1

    await db_session.refresh(owner_ctx.campaign)
    assert owner_ctx.campaign.status == "paused"
    states = await _activation_states(db_session, campaign_id)
    assert states and all(not running for running in states)


async def test_campaign_stop_from_draft_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
) -> None:
    await _prepare_runnable_campaign(db_session, owner_ctx)

    response = await auth_client.post(f"{BASE}{owner_ctx.campaign.id}/stop")
    assert response.status_code == 400
    assert "cannot be stopped" in response.json()["detail"]


async def test_campaign_lifecycle_start_stop_start_via_http(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    await _prepare_runnable_campaign(db_session, owner_ctx)
    campaign_id = owner_ctx.campaign.id

    assert (await auth_client.post(f"{BASE}{campaign_id}/start")).status_code == 200
    assert (await auth_client.post(f"{BASE}{campaign_id}/stop")).status_code == 200

    await db_session.refresh(owner_ctx.campaign)
    assert owner_ctx.campaign.status == "paused"

    mock_send_campaign_message["calls"].clear()
    restart = await auth_client.post(f"{BASE}{campaign_id}/start")
    assert restart.status_code == 200
    assert restart.json()["status"] == "started"

    await db_session.refresh(owner_ctx.campaign)
    assert owner_ctx.campaign.status == "active"
    assert len(mock_send_campaign_message["calls"]) == 1


async def test_campaign_start_foreign_returns_404(
    auth_client,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    foreign_id = await foreign_campaign_id(db_session)
    response = await auth_client.post(f"{BASE}{foreign_id}/start")
    assert response.status_code == 404
    assert mock_send_campaign_message["calls"] == []


async def test_campaign_start_system_owner_returns_200(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_send_campaign_message,
) -> None:
    system_campaign = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="System Lifecycle",
        status="draft",
        is_system=True,
    )
    db_session.add(system_campaign)
    await db_session.flush()
    db_session.add(
        CampaignChannel(campaign_id=system_campaign.id, channel_type="whatsapp")
    )
    await db_session.flush()

    response = await auth_client.post(f"{BASE}{system_campaign.id}/start")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "started"
    assert body["leads_dispatched"] == 0
    assert mock_send_campaign_message["calls"] == []


async def test_campaign_stop_foreign_returns_404(
    auth_client,
    db_session,
    clean_redis,
) -> None:
    foreign_id = await foreign_campaign_id(db_session)
    response = await auth_client.post(f"{BASE}{foreign_id}/stop")
    assert response.status_code == 404
