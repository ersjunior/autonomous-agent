"""Camada 3 — PATCH /agents/{id}/identity (override por agente, exceção is_system)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from agents.identity import IDENTITY_CONFIG_KEY
from app.core.authorization import SYSTEM_RECORD_EDIT_DETAIL
from app.models.agent import Agent
from tests.api.ownership_helpers import foreign_agent_id
from tests.integration.helpers import get_admin_user

pytestmark = pytest.mark.api

BASE = "/api/v1/agents/"

SAMPLE_OVERRIDE = {
    "company_name": "Override Corp",
    "display_name": "Override Display",
    "tone": "informal",
    "business_context": "Contexto específico do agente.",
    "greeting_hint": "Use o primeiro nome.",
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


def _identity_url(agent_id: uuid.UUID | str) -> str:
    return f"{BASE}{agent_id}/identity"


async def test_agent_identity_patch_custom_agent_success(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    response = await auth_client.patch(
        _identity_url(owner_ctx.agent.id),
        json=SAMPLE_OVERRIDE,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == SAMPLE_OVERRIDE["company_name"]
    assert body["display_name"] == SAMPLE_OVERRIDE["display_name"]

    await db_session.refresh(owner_ctx.agent)
    identity = owner_ctx.agent.config.get(IDENTITY_CONFIG_KEY, {})
    assert identity["company_name"] == SAMPLE_OVERRIDE["company_name"]
    assert owner_ctx.agent.config.get("tipo") is None or isinstance(
        owner_ctx.agent.config, dict
    )


async def test_agent_identity_patch_system_agent_success(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    system_id = await _system_agent_id(db_session)
    response = await auth_client.patch(
        _identity_url(system_id),
        json={"company_name": "Sistema Override", "tone": "formal"},
    )
    assert response.status_code == 200
    assert response.json()["company_name"] == "Sistema Override"
    assert response.json()["tone"] == "formal"

    agent = await db_session.get(Agent, system_id)
    assert agent is not None
    identity = agent.config.get(IDENTITY_CONFIG_KEY, {})
    assert identity["company_name"] == "Sistema Override"
    assert identity["tone"] == "formal"


async def test_agent_identity_put_general_system_still_403(
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


async def test_agent_identity_patch_foreign_agent_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = await foreign_agent_id(db_session)
    response = await auth_client.patch(
        _identity_url(foreign_id),
        json={"company_name": "Não deve gravar"},
    )
    assert response.status_code == 404


async def test_agent_identity_patch_empty_fields_clear_override(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    agent_id = owner_ctx.agent.id
    await auth_client.patch(_identity_url(agent_id), json=SAMPLE_OVERRIDE)

    cleared = {
        "company_name": "",
        "display_name": None,
        "tone": "   ",
        "business_context": "",
        "greeting_hint": None,
    }
    response = await auth_client.patch(_identity_url(agent_id), json=cleared)
    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] is None
    assert body["display_name"] is None
    assert body["tone"] is None

    await db_session.refresh(owner_ctx.agent)
    assert IDENTITY_CONFIG_KEY not in (owner_ctx.agent.config or {})


async def test_agent_identity_patch_preserves_other_config_keys(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    owner_ctx.agent.config = {"tipo": "inbound", IDENTITY_CONFIG_KEY: {"tone": "antigo"}}
    await db_session.commit()

    response = await auth_client.patch(
        _identity_url(owner_ctx.agent.id),
        json={"company_name": "Nova Empresa"},
    )
    assert response.status_code == 200

    await db_session.refresh(owner_ctx.agent)
    assert owner_ctx.agent.config["tipo"] == "inbound"
    assert owner_ctx.agent.config[IDENTITY_CONFIG_KEY]["company_name"] == "Nova Empresa"
    assert "tone" not in owner_ctx.agent.config[IDENTITY_CONFIG_KEY]


async def test_agent_identity_patch_requires_auth(client, owner_ctx) -> None:
    response = await client.patch(
        _identity_url(owner_ctx.agent.id),
        json={"company_name": "X"},
    )
    assert response.status_code == 401
