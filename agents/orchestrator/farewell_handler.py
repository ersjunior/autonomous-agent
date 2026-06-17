"""Encerramento autônomo de ligação por voz (despedida + hangup)."""

from __future__ import annotations

from agents.memory.booking_state import get_booking_state, is_active_booking_phase
from agents.orchestrator.state import AgentState
from agents.workers.voice_intent_heuristic import (
    matches_farewell_heuristic,
    matches_wrap_up_decline,
)
from app.services.voice_call_state import clear_wrap_up_pending, get_wrap_up_pending

VOICE_FAREWELL_PHRASE = "Até logo, obrigado pelo contato!"


def _is_voice_channel(channel: str) -> bool:
    return (channel or "").lower() == "voice"


def _booking_consumed_turn(state: AgentState) -> bool:
    if state.get("booking_phase") is not None:
        return True
    if (state.get("booking_context") or "").strip():
        return True
    channel = (state.get("channel") or "").lower()
    booking = get_booking_state(channel, state["user_id"])
    if booking and is_active_booking_phase(booking.get("phase")):
        return True
    return False


def _should_end_call(state: AgentState) -> bool:
    if not _is_voice_channel(state.get("channel", "")):
        return False
    if state.get("should_escalate"):
        return False
    if _booking_consumed_turn(state):
        return False

    intent = (state.get("intent") or "").lower()
    if intent == "farewell" and float(state.get("confidence") or 0) >= 0.9:
        return True

    call_sid = (state.get("twilio_call_sid") or "").strip()
    if call_sid and get_wrap_up_pending(call_sid):
        message = (state.get("message") or "").strip()
        if matches_wrap_up_decline(message):
            return True

    return False


def process_farewell_turn(state: AgentState) -> dict:
    """
    Se o turno for despedida válida, retorna resposta determinística + should_hangup.

    No-op quando booking/escalação consumiram o turno ou sinais são ambíguos.
    """
    if not _should_end_call(state):
        return {}

    call_sid = (state.get("twilio_call_sid") or "").strip()
    if call_sid:
        clear_wrap_up_pending(call_sid)

    return {
        "response": VOICE_FAREWELL_PHRASE,
        "should_hangup": True,
        "intent": "farewell",
    }
