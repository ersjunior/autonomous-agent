"""Unit tests — resposta determinística de agendamento por voz (sem LLM)."""

from __future__ import annotations

import pytest

from agents.orchestrator.graph import generate_response

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_generate_response_skips_llm_for_voice_booking_phrase(monkeypatch) -> None:
    async def _no_rag(state):
        raise AssertionError("RAG não deve rodar")

    async def _no_llm(*args, **kwargs):
        raise AssertionError("LLM não deve rodar")

    monkeypatch.setattr("agents.orchestrator.graph._fetch_rag_context", _no_rag)
    monkeypatch.setattr("agents.orchestrator.graph.run_generate_response", _no_llm)

    state = {
        "message": "sim",
        "channel": "voice",
        "user_id": "+5511999999999",
        "intent": "other",
        "confidence": 0.9,
        "entities": {},
        "response": "Tenho quarta às quatorze horas, serve para você?",
        "should_escalate": False,
        "conversation_history": [],
        "booking_phase": "awaiting_choice",
    }

    result = await generate_response(state)

    assert result["response"] == state["response"]
    assert result["response_ms"] == 0.0
    assert result["rag_ms"] == 0.0
