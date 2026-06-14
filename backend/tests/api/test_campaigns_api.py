"""Camada 3 — CRUD + ownership de /campaigns via API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.authorization import SYSTEM_RECORD_DELETE_DETAIL, SYSTEM_RECORD_EDIT_DETAIL
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from tests.api.ownership_helpers import foreign_campaign_id

pytestmark = pytest.mark.api

BASE = "/api/v1/campaigns/"


def _campaign_payload(agent_id: str, *, suffix: str | None = None) -> dict:
    tag = suffix or uuid.uuid4().hex[:8]
    return {
        "name": f"Campaign_{tag}",
        "agent_id": agent_id,
        "channel_types": ["whatsapp"],
    }


async def test_campaigns_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_campaigns_list_includes_owner_excludes_foreign(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    foreign_id = str(await foreign_campaign_id(db_session))

    response = await auth_client.get(BASE)
    assert response.status_code == 200

    ids = {item["id"] for item in response.json()}
    assert str(owner_ctx.campaign.id) in ids
    assert foreign_id not in ids


async def test_campaigns_create_returns_201_with_is_system_and_persists(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    payload = _campaign_payload(str(owner_ctx.agent.id))
    response = await auth_client.post(BASE, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == payload["name"]
    assert body["agent_id"] == str(owner_ctx.agent.id)
    assert body["channel_types"] == ["whatsapp"]
    assert body["is_system"] is False
    assert body["status"] == "draft"
    assert body["leads_count"] == 0
    assert "created_at" in body

    persisted = await db_session.get(Campaign, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.user_id == owner_ctx.user.id


async def test_campaigns_create_empty_channel_types_returns_422(auth_client, owner_ctx) -> None:
    response = await auth_client.post(
        BASE,
        json={
            "name": "Sem canais",
            "agent_id": str(owner_ctx.agent.id),
            "channel_types": [],
        },
    )
    assert response.status_code == 422


async def test_campaigns_create_foreign_agent_returns_404(auth_client) -> None:
    response = await auth_client.post(
        BASE,
        json=_campaign_payload(str(uuid.uuid4())),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


async def test_campaigns_get_own_returns_200(auth_client, owner_ctx) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.campaign.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(owner_ctx.campaign.id)
    assert "is_system" in body


async def test_campaigns_get_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_campaign_id(db_session))
    response = await auth_client.get(f"{BASE}{foreign_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Campaign not found"


async def test_campaigns_get_missing_returns_404(auth_client) -> None:
    response = await auth_client.get(f"{BASE}{uuid.uuid4()}")
    assert response.status_code == 404


async def test_campaigns_update_own_returns_200(auth_client, owner_ctx) -> None:
    response = await auth_client.put(
        f"{BASE}{owner_ctx.campaign.id}",
        json={"name": "Campanha Renomeada", "channel_types": ["telegram"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Campanha Renomeada"
    assert body["channel_types"] == ["telegram"]


async def test_campaigns_update_system_returns_403(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    system_campaign = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="System Campaign API",
        status="draft",
        is_system=True,
    )
    db_session.add(system_campaign)
    await db_session.flush()

    response = await auth_client.put(
        f"{BASE}{system_campaign.id}",
        json={"name": "Tentativa"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_EDIT_DETAIL


async def test_campaigns_update_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_campaign_id(db_session))
    response = await auth_client.put(
        f"{BASE}{foreign_id}",
        json={"name": "Não deve alterar"},
    )
    assert response.status_code == 404


async def test_campaigns_delete_own_returns_204(auth_client, owner_ctx, db_session) -> None:
    create = await auth_client.post(
        BASE,
        json=_campaign_payload(str(owner_ctx.agent.id)),
    )
    campaign_id = create.json()["id"]

    response = await auth_client.delete(f"{BASE}{campaign_id}")
    assert response.status_code == 204
    assert await db_session.get(Campaign, uuid.UUID(campaign_id)) is None


async def test_campaigns_delete_system_returns_403(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    system_campaign = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="System Delete API",
        status="draft",
        is_system=True,
    )
    db_session.add(system_campaign)
    await db_session.flush()

    response = await auth_client.delete(f"{BASE}{system_campaign.id}")
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_DELETE_DETAIL


async def test_campaigns_delete_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_campaign_id(db_session))
    response = await auth_client.delete(f"{BASE}{foreign_id}")
    assert response.status_code == 404


async def test_campaigns_create_receptive_agent_allowed_with_201(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    """RECEPTIVE gera warning no servidor, mas create retorna 201 (comportamento real)."""
    receptive = (
        await db_session.execute(
            select(Agent).where(Agent.name == "Agente_Receptivo")
        )
    ).scalar_one()
    assert receptive.mode == AgentMode.RECEPTIVE

    response = await auth_client.post(
        BASE,
        json=_campaign_payload(str(receptive.id), suffix="receptive"),
    )
    assert response.status_code == 201
