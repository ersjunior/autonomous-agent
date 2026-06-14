"""Camada 3 — CRUD + ownership de /agents via API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.authorization import SYSTEM_RECORD_DELETE_DETAIL, SYSTEM_RECORD_EDIT_DETAIL
from app.models.agent import Agent
from tests.api.ownership_helpers import foreign_agent_id
from tests.integration.helpers import get_admin_user

pytestmark = pytest.mark.api

BASE = "/api/v1/agents/"


def _agent_payload(*, suffix: str | None = None) -> dict:
    tag = suffix or uuid.uuid4().hex[:8]
    return {
        "name": f"Agent_{tag}",
        "description": "API test agent",
        "mode": "ACTIVE",
        "config": {"tone": "neutral"},
    }


async def _system_agent_id(db_session) -> uuid.UUID:
    admin = await get_admin_user(db_session)
    agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Ativo",
            )
        )
    ).scalar_one()
    return agent.id


async def test_agents_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_agents_list_includes_owner_and_system_excludes_foreign(
    auth_client,
    owner_ctx,
    system_seeds,
    db_session,
) -> None:
    foreign_id = str(await foreign_agent_id(db_session))
    system_id = str(await _system_agent_id(db_session))

    response = await auth_client.get(BASE)
    assert response.status_code == 200

    ids = {item["id"] for item in response.json()}
    assert str(owner_ctx.agent.id) in ids
    assert system_id in ids
    assert foreign_id not in ids
    assert all(item["mode"] in ("ACTIVE", "RECEPTIVE") for item in response.json())


async def test_agents_create_returns_201_and_persists(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    payload = _agent_payload()
    response = await auth_client.post(BASE, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == payload["name"]
    assert body["mode"] == "ACTIVE"
    assert body["is_system"] is False
    assert body["status"] == "draft"
    assert "id" in body

    persisted = await db_session.get(Agent, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.user_id == owner_ctx.user.id


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "sem nome", "mode": "ACTIVE"},
        {"name": "Bad mode", "mode": "INVALID"},
    ],
)
async def test_agents_create_invalid_payload_returns_422(
    auth_client,
    payload: dict,
) -> None:
    response = await auth_client.post(BASE, json=payload)
    assert response.status_code == 422


async def test_agents_get_own_returns_200(auth_client, owner_ctx) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.agent.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(owner_ctx.agent.id)


async def test_agents_get_foreign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = str(await foreign_agent_id(db_session))
    response = await auth_client.get(f"{BASE}{foreign_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


async def test_agents_get_missing_returns_404(auth_client) -> None:
    missing = uuid.uuid4()
    response = await auth_client.get(f"{BASE}{missing}")
    assert response.status_code == 404


async def test_agents_update_own_returns_200(auth_client, owner_ctx, db_session) -> None:
    response = await auth_client.put(
        f"{BASE}{owner_ctx.agent.id}",
        json={"name": "Agente Atualizado", "mode": "RECEPTIVE"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Agente Atualizado"
    assert body["mode"] == "RECEPTIVE"

    await db_session.refresh(owner_ctx.agent)
    assert owner_ctx.agent.name == "Agente Atualizado"


async def test_agents_update_system_returns_403(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    system_id = await _system_agent_id(db_session)
    response = await auth_client.put(
        f"{BASE}{system_id}",
        json={"name": "Tentativa System"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_EDIT_DETAIL


async def test_agents_update_foreign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = str(await foreign_agent_id(db_session))
    response = await auth_client.put(
        f"{BASE}{foreign_id}",
        json={"name": "Não deve alterar"},
    )
    assert response.status_code == 404


async def test_agents_delete_own_returns_204(auth_client, db_session) -> None:
    create = await auth_client.post(BASE, json=_agent_payload())
    agent_id = create.json()["id"]

    response = await auth_client.delete(f"{BASE}{agent_id}")
    assert response.status_code == 204

    assert await db_session.get(Agent, uuid.UUID(agent_id)) is None


async def test_agents_delete_system_returns_403(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    system_id = await _system_agent_id(db_session)
    response = await auth_client.delete(f"{BASE}{system_id}")
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_DELETE_DETAIL


async def test_agents_delete_foreign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = str(await foreign_agent_id(db_session))
    response = await auth_client.delete(f"{BASE}{foreign_id}")
    assert response.status_code == 404
