"""Unit tests — seed agent lookup reloads config (no process-level cache)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.identity import IDENTITY_CONFIG_KEY
from app.models.agent import Agent, AgentMode
from worker.tasks.conversation_routing import _get_system_agent_by_mode

pytestmark = pytest.mark.unit


def _seed_agent(mode: AgentMode, company_name: str) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Agente_Receptivo" if mode == AgentMode.RECEPTIVE else "Agente_Ativo",
        mode=mode,
        is_system=True,
        config={IDENTITY_CONFIG_KEY: {"company_name": company_name}},
    )


@pytest.mark.asyncio
async def test_get_system_agent_by_mode_reloads_from_db_each_call() -> None:
    """Each inbound turn must see updated agent.config.identity without worker restart."""
    stale = _seed_agent(AgentMode.RECEPTIVE, "Empresa Antiga")
    fresh = _seed_agent(AgentMode.RECEPTIVE, "Empresa Nova")
    agents = iter([stale, fresh])
    execute_calls = 0

    async def fake_execute(_query):
        nonlocal execute_calls
        execute_calls += 1
        result = MagicMock()
        result.scalar_one_or_none = lambda: next(agents)
        return result

    session = AsyncMock()
    session.execute = fake_execute

    first = await _get_system_agent_by_mode(session, AgentMode.RECEPTIVE)
    second = await _get_system_agent_by_mode(session, AgentMode.RECEPTIVE)

    assert first.config[IDENTITY_CONFIG_KEY]["company_name"] == "Empresa Antiga"
    assert second.config[IDENTITY_CONFIG_KEY]["company_name"] == "Empresa Nova"
    assert execute_calls == 2
