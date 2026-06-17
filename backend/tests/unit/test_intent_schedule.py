"""Testes unitários — intent schedule."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.workers.intent_agent import IntentResult, identify_intent

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_identify_intent_schedule_mocked() -> None:
    expected = IntentResult(
        intent="schedule",
        confidence=0.92,
        entities={
            "preferred_date": "amanhã",
            "appointment_type": "reunião",
        },
    )
    with patch("agents.workers.intent_agent.ProviderFactory.get_llm") as mock_factory:
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=expected)
        mock_factory.return_value = mock_llm

        result = await identify_intent("Quero agendar uma reunião para amanhã", [])

    assert result.intent == "schedule"
    assert result.entities.get("appointment_type") == "reunião"
    mock_llm.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_identify_intent_schedule_visit_phrase() -> None:
    expected = IntentResult(
        intent="schedule",
        confidence=0.88,
        entities={"appointment_type": "visita"},
    )
    with patch("agents.workers.intent_agent.ProviderFactory.get_llm") as mock_factory:
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=expected)
        mock_factory.return_value = mock_llm

        result = await identify_intent("Posso marcar uma visita?", [])

    assert result.intent == "schedule"
