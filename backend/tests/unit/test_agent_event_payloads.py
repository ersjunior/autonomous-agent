"""Unit tests — agent fields in monitoring event payloads."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.orchestrator.graph import _agent_event_fields, identify_intent, send_response
from agents.orchestrator.router import route_message
from agents.orchestrator.state import AgentState

pytestmark = pytest.mark.unit


def test_agent_event_fields_includes_optional_ids() -> None:
    state: AgentState = {
        "message": "oi",
        "channel": "telegram",
        "user_id": "123",
        "intent": "",
        "confidence": 0.0,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "agent_id": "uuid-agent",
        "agent_name": "Agente Teste",
    }
    fields = _agent_event_fields(state)
    assert fields == {"agent_id": "uuid-agent", "agent_name": "Agente Teste"}


def test_agent_event_fields_omits_when_missing() -> None:
    state: AgentState = {
        "message": "oi",
        "channel": "telegram",
        "user_id": "123",
        "intent": "",
        "confidence": 0.0,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
    }
    assert _agent_event_fields(state) == {}


@pytest.mark.asyncio
async def test_route_message_received_includes_agent_context() -> None:
    captured: list[dict] = []

    async def fake_publish(_event_type: str, payload: dict) -> None:
        captured.append(payload)

    with (
        patch("agents.orchestrator.router.publish_event_async", side_effect=fake_publish),
        patch(
            "agents.orchestrator.router.build_initial_state",
            return_value={"response": "ok"},
        ),
        patch("agents.orchestrator.graph.agent_graph") as mock_graph,
        patch(
            "app.services.settings_sync.ensure_settings_fresh_async",
            new_callable=AsyncMock,
        ),
    ):
        mock_graph.ainvoke = AsyncMock(return_value={"response": "ok"})
        await route_message(
            "olá",
            "telegram",
            "5043259127",
            notify_received=True,
            agent_context={
                "agent_id": "a1",
                "agent_name": "Receptivo",
            },
        )

    assert len(captured) == 1
    assert captured[0]["agent_id"] == "a1"
    assert captured[0]["agent_name"] == "Receptivo"
    assert captured[0]["channel"] == "telegram"


@pytest.mark.asyncio
async def test_identify_intent_publish_includes_agent_from_state() -> None:
    captured: list[dict] = []

    async def fake_publish(_event_type: str, payload: dict) -> None:
        captured.append(payload)

    state: AgentState = {
        "message": "preciso de ajuda",
        "channel": "whatsapp",
        "user_id": "5511999999999",
        "intent": "",
        "confidence": 0.0,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "agent_id": "agent-uuid",
        "agent_name": "Vendas",
    }

    with (
        patch("agents.orchestrator.graph.publish_event_async", side_effect=fake_publish),
        patch(
            "agents.orchestrator.graph.run_identify_intent",
            new_callable=AsyncMock,
        ) as mock_intent,
        patch(
            "agents.orchestrator.graph._short_term_memory.get_history",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        from agents.workers.intent_agent import IntentResult

        mock_intent.return_value = IntentResult(
            intent="question",
            confidence=0.9,
            entities={},
            complaint_severity="low",
        )
        await identify_intent(state)

    assert captured[0]["agent_id"] == "agent-uuid"
    assert captured[0]["agent_name"] == "Vendas"
    assert captured[0]["intent"] == "question"


@pytest.mark.asyncio
async def test_send_response_publish_includes_agent_from_state() -> None:
    captured: list[tuple[str, dict]] = []

    async def fake_publish(event_type: str, payload: dict) -> None:
        captured.append((event_type, payload))

    state: AgentState = {
        "message": "oi",
        "channel": "telegram",
        "user_id": "123",
        "intent": "greeting",
        "confidence": 1.0,
        "entities": {},
        "response": "Olá!",
        "should_escalate": False,
        "conversation_history": [],
        "agent_id": "agent-uuid",
        "agent_name": "Suporte",
    }

    with (
        patch("agents.orchestrator.graph.publish_event_async", side_effect=fake_publish),
        patch(
            "agents.orchestrator.graph._short_term_memory.save_history",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.orchestrator.graph._long_term_memory.save_interaction",
            new_callable=AsyncMock,
        ),
    ):
        await send_response(state)

    event_type, payload = captured[0]
    assert event_type == "response_sent"
    assert payload["agent_id"] == "agent-uuid"
    assert payload["agent_name"] == "Suporte"
