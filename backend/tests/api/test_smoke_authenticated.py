"""Camada 3 — smoke do auth_client (override de get_current_user)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.api


async def test_auth_client_lists_agents(auth_client, owner_ctx, system_seeds) -> None:
    response = await auth_client.get("/api/v1/agents/")

    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    ids = {agent["id"] for agent in agents}
    assert str(owner_ctx.agent.id) in ids
