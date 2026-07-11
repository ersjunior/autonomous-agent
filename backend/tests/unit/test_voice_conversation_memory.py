"""Voice short-term dialog history is isolated per CallSid, not per phone number."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.memory.short_term import (
    VOICE_CALL_HISTORY_TTL_SECONDS,
    conversation_memory_key,
)
from agents.orchestrator.graph import _dialog_memory_key, identify_intent, send_response
from agents.orchestrator.state import AgentState

pytestmark = pytest.mark.unit

_USER = "+5511948660628"
_CALL_A = "CA-call-a-test-0001"
_CALL_B = "CA-call-b-test-0002"


def test_conversation_memory_key_voice_uses_call_sid() -> None:
    assert conversation_memory_key("voice", _USER, twilio_call_sid=_CALL_A) == _CALL_A


def test_conversation_memory_key_non_voice_uses_user_id() -> None:
    assert conversation_memory_key("telegram", _USER, twilio_call_sid=_CALL_A) == _USER
    assert conversation_memory_key("whatsapp", _USER, twilio_call_sid=_CALL_A) == _USER


def test_conversation_memory_key_voice_without_call_sid_falls_back_to_user_id() -> None:
    assert conversation_memory_key("voice", _USER, twilio_call_sid=None) == _USER
    assert conversation_memory_key("voice", _USER, twilio_call_sid="") == _USER


def test_dialog_memory_key_from_state() -> None:
    state: AgentState = {
        "message": "oi",
        "channel": "voice",
        "user_id": _USER,
        "intent": "",
        "confidence": 0.0,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "twilio_call_sid": _CALL_A,
    }
    assert _dialog_memory_key(state) == _CALL_A


@pytest.mark.asyncio
async def test_voice_two_calls_same_user_do_not_share_dialog_history() -> None:
    """Second call must not read dialog history saved under the first CallSid."""
    store: dict[str, list[dict]] = {}

    async def fake_get(key: str, *, channel: str | None = None) -> list[dict]:
        return list(store.get(key, []))

    async def fake_save(key: str, history: list[dict], *, channel: str | None = None) -> None:
        store[key] = list(history)

    base: AgentState = {
        "message": "",
        "channel": "voice",
        "user_id": _USER,
        "intent": "greeting",
        "confidence": 0.9,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "twilio_call_sid": _CALL_A,
    }

    with (
        patch(
            "agents.orchestrator.graph._short_term_memory.get_history",
            side_effect=fake_get,
        ),
        patch(
            "agents.orchestrator.graph._short_term_memory.save_history",
            side_effect=fake_save,
        ),
        patch(
            "agents.orchestrator.graph._long_term_memory.save_interaction",
            new_callable=AsyncMock,
        ),
        patch("agents.orchestrator.graph.publish_event_async", new_callable=AsyncMock),
        patch(
            "agents.orchestrator.graph.identify_intent_voice_heuristic",
            return_value=type(
                "R",
                (),
                {
                    "intent": "greeting",
                    "confidence": 0.9,
                    "entities": {},
                    "complaint_severity": "low",
                },
            )(),
        ),
    ):
        call_a_turn1 = {**base, "message": "Olá", "response": "Olá! Como posso ajudar?"}
        await send_response(call_a_turn1)

        call_b_state = {**base, "twilio_call_sid": _CALL_B, "message": "Olá", "response": ""}
        result_b = await identify_intent(call_b_state)

    assert _CALL_A in store
    assert _CALL_B not in store
    assert result_b["conversation_history"] == []


@pytest.mark.asyncio
async def test_voice_same_call_retains_intra_call_dialog_history() -> None:
    """Turns within the same CallSid must accumulate dialog context."""
    store: dict[str, list[dict]] = {}

    async def fake_get(key: str, *, channel: str | None = None) -> list[dict]:
        return list(store.get(key, []))

    async def fake_save(key: str, history: list[dict], *, channel: str | None = None) -> None:
        store[key] = list(history)

    state: AgentState = {
        "message": "Meu nome é João",
        "channel": "voice",
        "user_id": _USER,
        "intent": "other",
        "confidence": 0.9,
        "entities": {},
        "response": "Prazer, João!",
        "should_escalate": False,
        "conversation_history": [],
        "twilio_call_sid": _CALL_A,
    }

    with (
        patch(
            "agents.orchestrator.graph._short_term_memory.get_history",
            side_effect=fake_get,
        ),
        patch(
            "agents.orchestrator.graph._short_term_memory.save_history",
            side_effect=fake_save,
        ),
        patch(
            "agents.orchestrator.graph._long_term_memory.save_interaction",
            new_callable=AsyncMock,
        ),
        patch("agents.orchestrator.graph.publish_event_async", new_callable=AsyncMock),
    ):
        await send_response(state)
        turn2 = await identify_intent(
            {
                **state,
                "message": "Qual é o meu nome?",
                "response": "",
                "conversation_history": [],
            }
        )

    assert len(store[_CALL_A]) == 2
    assert store[_CALL_A][0] == {"role": "user", "content": "Meu nome é João"}
    assert turn2["conversation_history"] == store[_CALL_A]


@pytest.mark.asyncio
async def test_send_response_long_term_still_uses_phone_user_id() -> None:
    """RAG/long-term memory must remain keyed by contact phone, not CallSid."""
    state: AgentState = {
        "message": "oi",
        "channel": "voice",
        "user_id": _USER,
        "intent": "greeting",
        "confidence": 1.0,
        "entities": {},
        "response": "Olá!",
        "should_escalate": False,
        "conversation_history": [],
        "twilio_call_sid": _CALL_A,
    }

    with (
        patch(
            "agents.orchestrator.graph._short_term_memory.save_history",
            new_callable=AsyncMock,
        ) as mock_save,
        patch(
            "agents.orchestrator.graph._long_term_memory.save_interaction",
            new_callable=AsyncMock,
        ) as mock_lt,
        patch("agents.orchestrator.graph.publish_event_async", new_callable=AsyncMock),
    ):
        await send_response(state)

    mock_save.assert_awaited_once()
    assert mock_save.await_args.args[0] == _CALL_A
    mock_lt.assert_awaited_once()
    assert mock_lt.await_args.args[0] == _USER


def test_voice_call_history_ttl_is_longer_than_contact_ttl() -> None:
    from agents.memory.short_term import TTL_SECONDS

    assert VOICE_CALL_HISTORY_TTL_SECONDS > TTL_SECONDS
