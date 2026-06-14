"""Unit tests — roteamento inbound de voz (sempre RECEPTIVE)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent import Agent, AgentMode
from app.models.lead import Lead
from worker.tasks.conversation_routing import resolve_inbound_agent

pytestmark = pytest.mark.unit


def _make_agent(name: str, mode: AgentMode) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name=name,
        mode=mode,
        is_system=True,
    )


@pytest.mark.asyncio
async def test_resolve_inbound_agent_voice_force_receptive_skips_active(monkeypatch) -> None:
    """Ligação inbound: force_receptive ignora conversa ACTIVE aberta no canal voice."""
    receptive = _make_agent("Agente_Receptivo", AgentMode.RECEPTIVE)
    active = _make_agent("Agente_Ativo", AgentMode.ACTIVE)
    lead = Lead(id=uuid.uuid4(), user_id=uuid.uuid4(), telefone_1="+5511999999999")

    open_interaction = MagicMock()
    open_interaction.status = "em_andamento"
    open_interaction.campaign = MagicMock()
    open_interaction.campaign.agent = active

    async def fake_get_latest(session, lead_id, channel):
        assert channel == "voice"
        return open_interaction

    async def fake_get_system(session, mode):
        assert mode == AgentMode.RECEPTIVE
        return receptive

    monkeypatch.setattr(
        "worker.tasks.conversation_routing.get_latest_lead_interaction",
        fake_get_latest,
    )
    monkeypatch.setattr(
        "worker.tasks.conversation_routing._get_system_agent_by_mode",
        fake_get_system,
    )
    monkeypatch.setattr(
        "worker.tasks.conversation_routing.is_active_conversation_open",
        lambda interaction: True,
    )

    agent = await resolve_inbound_agent(
        AsyncMock(),
        lead,
        "voice",
        force_receptive=True,
    )

    assert agent.mode == AgentMode.RECEPTIVE
    assert agent.name == "Agente_Receptivo"


@pytest.mark.asyncio
async def test_resolve_inbound_agent_whatsapp_keeps_active_when_open(monkeypatch) -> None:
    """WhatsApp inbound sem force_receptive continua no ACTIVE com conversa aberta."""
    active = _make_agent("Agente_Ativo", AgentMode.ACTIVE)
    lead = Lead(id=uuid.uuid4(), user_id=uuid.uuid4(), telefone_1="+5511999999999")

    open_interaction = MagicMock()
    open_interaction.status = "em_andamento"
    open_interaction.campaign = MagicMock()
    open_interaction.campaign.agent = active

    async def fake_get_latest(session, lead_id, channel):
        assert channel == "whatsapp"
        return open_interaction

    async def fake_get_system(session, mode):
        return active

    monkeypatch.setattr(
        "worker.tasks.conversation_routing.get_latest_lead_interaction",
        fake_get_latest,
    )
    monkeypatch.setattr(
        "worker.tasks.conversation_routing._get_system_agent_by_mode",
        fake_get_system,
    )
    monkeypatch.setattr(
        "worker.tasks.conversation_routing.is_active_conversation_open",
        lambda interaction: True,
    )

    agent = await resolve_inbound_agent(AsyncMock(), lead, "whatsapp")

    assert agent.mode == AgentMode.ACTIVE
    assert agent.name == "Agente_Ativo"
