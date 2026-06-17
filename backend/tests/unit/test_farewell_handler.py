"""Unit tests — encerramento autônomo por voz (farewell + wrap-up)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from agents.orchestrator.farewell_handler import (
    VOICE_FAREWELL_PHRASE,
    process_farewell_turn,
)
from agents.orchestrator.graph import generate_response, handle_farewell

pytestmark = pytest.mark.unit


def _voice_state(**overrides) -> dict:
    state = {
        "message": "tchau",
        "channel": "voice",
        "user_id": "+5511999999999",
        "intent": "farewell",
        "confidence": 0.92,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "owner_user_id": str(uuid4()),
        "lead_id": str(uuid4()),
        "twilio_call_sid": "CA-farewell-test",
    }
    state.update(overrides)
    return state


def test_farewell_explicit_sets_hangup() -> None:
    with (
        patch(
            "agents.orchestrator.farewell_handler.get_booking_state",
            return_value=None,
        ),
        patch(
            "agents.orchestrator.farewell_handler.clear_wrap_up_pending",
        ) as clear_wrap,
    ):
        result = process_farewell_turn(_voice_state(message="tchau"))

    clear_wrap.assert_called_once_with("CA-farewell-test")
    assert result.get("should_hangup") is True
    assert result.get("response") == VOICE_FAREWELL_PHRASE
    assert result.get("intent") == "farewell"


def test_farewell_skipped_when_booking_active() -> None:
    with patch(
        "agents.orchestrator.farewell_handler.get_booking_state",
        return_value={"phase": "awaiting_choice", "voice_mode": True},
    ):
        result = process_farewell_turn(
            _voice_state(message="não", intent="question", confidence=0.85)
        )

    assert result == {}


def test_wrap_up_decline_hangup() -> None:
    with (
        patch(
            "agents.orchestrator.farewell_handler.get_booking_state",
            return_value=None,
        ),
        patch(
            "agents.orchestrator.farewell_handler.get_wrap_up_pending",
            return_value=True,
        ),
        patch(
            "agents.orchestrator.farewell_handler.clear_wrap_up_pending",
        ) as clear_wrap,
    ):
        result = process_farewell_turn(
            _voice_state(message="não", intent="question", confidence=0.85)
        )

    assert result.get("should_hangup") is True
    clear_wrap.assert_called_once_with("CA-farewell-test")


def test_wrap_up_without_pending_no_hangup_on_bare_nao() -> None:
    with (
        patch(
            "agents.orchestrator.farewell_handler.get_booking_state",
            return_value=None,
        ),
        patch(
            "agents.orchestrator.farewell_handler.get_wrap_up_pending",
            return_value=False,
        ),
    ):
        result = process_farewell_turn(
            _voice_state(message="não", intent="question", confidence=0.85)
        )

    assert result == {}


@pytest.mark.asyncio
async def test_generate_response_skips_llm_for_farewell_hangup(monkeypatch) -> None:
    async def _no_rag(state):
        raise AssertionError("RAG não deve rodar")

    async def _no_llm(*args, **kwargs):
        raise AssertionError("LLM não deve rodar")

    monkeypatch.setattr("agents.orchestrator.graph._fetch_rag_context", _no_rag)
    monkeypatch.setattr("agents.orchestrator.graph.run_generate_response", _no_llm)

    state = {
        "message": "tchau",
        "channel": "voice",
        "user_id": "+5511999999999",
        "intent": "farewell",
        "confidence": 0.92,
        "entities": {},
        "response": VOICE_FAREWELL_PHRASE,
        "should_hangup": True,
        "should_escalate": False,
        "conversation_history": [],
    }

    result = await generate_response(state)

    assert result["response"] == VOICE_FAREWELL_PHRASE
    assert result["response_ms"] == 0.0


@pytest.mark.asyncio
async def test_handle_farewell_after_booking_noop_when_booking_handled() -> None:
    state = _voice_state(
        message="sim",
        intent="other",
        response="Tenho quarta às nove horas, serve para você?",
        booking_phase="awaiting_choice",
    )
    result = await handle_farewell(state)
    assert result == {}
