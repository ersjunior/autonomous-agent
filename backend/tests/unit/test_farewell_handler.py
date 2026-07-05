"""Unit tests — encerramento autônomo por voz (farewell + wrap-up)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from agents.orchestrator.farewell_handler import (
    VOICE_FAREWELL_PHRASE,
    agent_response_is_farewell,
    agent_response_is_question,
    apply_hangup_decision,
    detect_user_farewell_signal,
    user_signals_farewell,
)
from agents.orchestrator.graph import finalize_hangup, generate_response, handle_farewell

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


class TestAgentResponseGuardrails:
    def test_question_mark_blocks_hangup(self) -> None:
        assert agent_response_is_question("Me conta mais sobre o que você procura?")
        assert agent_response_is_question("Fico à disposição! Posso ajudar?")

    def test_courtesy_without_question_is_not_farewell(self) -> None:
        assert not agent_response_is_farewell(
            "Fico à disposição para ajudar no que precisar."
        )
        assert not agent_response_is_farewell("Posso ajudar sim, me conta mais.")

    def test_unequivocal_farewell_detected(self) -> None:
        assert agent_response_is_farewell(VOICE_FAREWELL_PHRASE)
        assert agent_response_is_farewell("Até logo e tenha um bom dia!")


class TestUserFarewellSignal:
    def test_detects_explicit_user_farewell(self) -> None:
        with (
            patch(
                "agents.orchestrator.farewell_handler.get_booking_state",
                return_value=None,
            ),
            patch("agents.orchestrator.farewell_handler.clear_wrap_up_pending") as clear_wrap,
        ):
            result = detect_user_farewell_signal(_voice_state(message="tchau"))

        clear_wrap.assert_called_once_with("CA-farewell-test")
        assert result == {"user_farewell_signal": True}
        assert "should_hangup" not in result

    def test_skipped_when_booking_active(self) -> None:
        with patch(
            "agents.orchestrator.farewell_handler.get_booking_state",
            return_value={"phase": "awaiting_choice", "voice_mode": True},
        ):
            result = detect_user_farewell_signal(
                _voice_state(message="não", intent="question", confidence=0.85)
            )

        assert result == {}

    def test_non_farewell_user_message_no_signal(self) -> None:
        with patch(
            "agents.orchestrator.farewell_handler.get_booking_state",
            return_value=None,
        ):
            result = detect_user_farewell_signal(
                _voice_state(message="estou procurando um curso", intent="question")
            )

        assert result == {}

    def test_wrap_up_decline_sets_signal_not_immediate_hangup(self) -> None:
        with (
            patch(
                "agents.orchestrator.farewell_handler.get_booking_state",
                return_value=None,
            ),
            patch(
                "agents.orchestrator.farewell_handler.get_wrap_up_pending",
                return_value=True,
            ),
            patch("agents.orchestrator.farewell_handler.clear_wrap_up_pending") as clear_wrap,
        ):
            result = detect_user_farewell_signal(
                _voice_state(message="não", intent="question", confidence=0.85)
            )

        assert result == {"user_farewell_signal": True}
        clear_wrap.assert_called_once_with("CA-farewell-test")

    def test_wrap_up_bare_obrigado_does_not_signal(self) -> None:
        with (
            patch(
                "agents.orchestrator.farewell_handler.get_booking_state",
                return_value=None,
            ),
            patch(
                "agents.orchestrator.farewell_handler.get_wrap_up_pending",
                return_value=True,
            ),
        ):
            assert not user_signals_farewell(_voice_state(message="obrigado"))


class TestApplyHangupDecision:
    def test_courtesy_agent_non_farewell_user_no_hangup(self) -> None:
        state = _voice_state(
            message="estou procurando um curso",
            user_farewell_signal=False,
            response="Fico à disposição para ajudar no que precisar.",
        )
        assert apply_hangup_decision(state) == {"should_hangup": False}

    def test_agent_question_never_hangs_up_even_if_user_farewell(self) -> None:
        state = _voice_state(
            user_farewell_signal=True,
            response="Me conta mais sobre o que você procura? Fico à disposição!",
        )
        assert apply_hangup_decision(state) == {"should_hangup": False}

    def test_user_farewell_and_agent_farewell_hangs_up(self) -> None:
        state = _voice_state(
            user_farewell_signal=True,
            response=VOICE_FAREWELL_PHRASE,
        )
        assert apply_hangup_decision(state) == {
            "should_hangup": True,
            "response": VOICE_FAREWELL_PHRASE,
        }

    def test_user_farewell_but_agent_courtesy_no_hangup(self) -> None:
        state = _voice_state(
            user_farewell_signal=True,
            response="De nada! Fico à disposição para ajudar.",
        )
        assert apply_hangup_decision(state) == {"should_hangup": False}


@pytest.mark.asyncio
async def test_generate_response_runs_llm_when_user_farewell_signal(monkeypatch) -> None:
    """Com o novo critério, farewell do usuário não pula o LLM antes da dupla confirmação."""

    async def _fake_rag(state):
        return [], [], 0.0

    async def _fake_llm(*args, **kwargs):
        return "Até logo, obrigado pelo contato!"

    monkeypatch.setattr("agents.orchestrator.graph._fetch_rag_context", _fake_rag)
    monkeypatch.setattr("agents.orchestrator.graph.run_generate_response", _fake_llm)

    state = _voice_state(user_farewell_signal=True, response="")

    result = await generate_response(state)

    assert result["response"] == "Até logo, obrigado pelo contato!"


@pytest.mark.asyncio
async def test_finalize_hangup_after_llm_farewell() -> None:
    state = _voice_state(
        user_farewell_signal=True,
        response=VOICE_FAREWELL_PHRASE,
    )
    result = await finalize_hangup(state)
    assert result["should_hangup"] is True


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
