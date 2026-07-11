"""Unit tests — first-turn voice opening (STT misheard farewell)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agents.orchestrator.farewell_handler import (
    VOICE_FAREWELL_PHRASE,
    apply_hangup_decision,
    detect_user_farewell_signal,
)
from agents.orchestrator.graph import finalize_hangup, handle_farewell, identify_intent
from agents.workers.response_agent import (
    VOICE_OPENING_MISHEARD_PROMPT,
    build_response_messages,
)
from agents.workers.voice_intent_heuristic import (
    apply_voice_first_turn_intent,
    identify_intent_voice_heuristic,
)

pytestmark = pytest.mark.unit


def test_heuristic_farewell_stays_farewell_without_history_context() -> None:
    """Raw heuristic unchanged — reclassification happens in apply_voice_first_turn_intent."""
    result = identify_intent_voice_heuristic("Tchau, tchau.")
    assert result.intent == "farewell"


def test_apply_first_turn_reclassifies_farewell_to_greeting() -> None:
    raw = identify_intent_voice_heuristic("Tchau, tchau.")
    adjusted, opening = apply_voice_first_turn_intent(raw, conversation_history=[])
    assert opening is True
    assert adjusted.intent == "greeting"


def test_apply_first_turn_skipped_when_history_present() -> None:
    raw = identify_intent_voice_heuristic("tchau")
    adjusted, opening = apply_voice_first_turn_intent(
        raw,
        conversation_history=[{"role": "user", "content": "oi"}],
    )
    assert opening is False
    assert adjusted.intent == "farewell"


def test_greeting_first_turn_unchanged() -> None:
    raw = identify_intent_voice_heuristic("Olá")
    adjusted, opening = apply_voice_first_turn_intent(raw, conversation_history=[])
    assert opening is False
    assert adjusted.intent == "greeting"


def test_opening_prompt_injected_for_voice_opening_turn() -> None:
    messages = build_response_messages(
        "Tchau, tchau.",
        "greeting",
        {},
        [],
        "voice",
        voice_opening_turn=True,
    )
    contents = [m["content"] for m in messages if m["role"] == "system"]
    assert VOICE_OPENING_MISHEARD_PROMPT in contents


@pytest.mark.asyncio
async def test_identify_intent_first_turn_tchau_reclassified() -> None:
    state = {
        "message": "Tchau, tchau.",
        "channel": "voice",
        "user_id": "+5511999999999",
        "twilio_call_sid": "CA-first-turn",
    }
    with (
        patch(
            "agents.orchestrator.graph._short_term_memory.get_history",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("agents.orchestrator.graph.publish_event_async", new_callable=AsyncMock),
    ):
        result = await identify_intent(state)

    assert result["intent"] == "greeting"
    assert result["voice_opening_turn"] is True


@pytest.mark.asyncio
async def test_first_turn_farewell_transcript_no_farewell_signal() -> None:
    state = {
        "message": "Tchau, tchau.",
        "channel": "voice",
        "user_id": "+5511999999999",
        "should_escalate": False,
        "conversation_history": [],
        "twilio_call_sid": "CA-first-turn",
    }
    with patch(
        "agents.orchestrator.farewell_handler.get_booking_state",
        return_value=None,
    ):
        assert await handle_farewell(state) == {}


@pytest.mark.asyncio
async def test_first_turn_misheard_no_hangup_even_if_agent_farewell() -> None:
    """Defense in depth: hangup blocked; farewell signal also suppressed on turn 1."""
    state = {
        "message": "Tchau, tchau.",
        "channel": "voice",
        "user_id": "+5511999999999",
        "user_farewell_signal": False,
        "response": VOICE_FAREWELL_PHRASE,
        "conversation_history": [],
    }
    result = await finalize_hangup(state)
    assert result["should_hangup"] is False


def test_farewell_with_history_still_signals_and_hangs_up() -> None:
    history = [
        {"role": "user", "content": "quero um curso"},
        {"role": "assistant", "content": "Claro!"},
    ]
    state = {
        "message": "tchau",
        "channel": "voice",
        "user_id": "+5511999999999",
        "should_escalate": False,
        "conversation_history": history,
        "twilio_call_sid": "CA-farewell-legit",
        "owner_user_id": str(uuid4()),
    }
    with (
        patch(
            "agents.orchestrator.farewell_handler.get_booking_state",
            return_value=None,
        ),
        patch("agents.orchestrator.farewell_handler.clear_wrap_up_pending"),
    ):
        signal = detect_user_farewell_signal(state)
    assert signal == {"user_farewell_signal": True}

    hangup = apply_hangup_decision(
        {
            **state,
            **signal,
            "response": VOICE_FAREWELL_PHRASE,
        }
    )
    assert hangup["should_hangup"] is True
