"""Encerramento autônomo de ligação por voz (despedida + hangup)."""

from __future__ import annotations

import re
import unicodedata

from agents.memory.booking_state import get_booking_state, is_active_booking_phase
from agents.orchestrator.state import AgentState
from agents.workers.voice_intent_heuristic import (
    matches_farewell_heuristic,
    matches_wrap_up_decline,
)
from app.services.voice_call_state import clear_wrap_up_pending, get_wrap_up_pending

VOICE_FAREWELL_PHRASE = "Até logo, obrigado pelo contato!"

# Despedidas inequívocas na fala do agente (NÃO cortesia tipo "ajudar"/"disposição").
_AGENT_FAREWELL_PATTERNS = (
    r"\bate\s+(?:logo|mais|breve)\b",
    r"\bate\s+a\s+proxima\b",
    r"\btenha\s+um\s+bom\s+(?:dia|tarde|noite)\b",
    r"\bobrigad[oa]\s+pelo\s+contato\b",
    r"\bfoi\s+um\s+prazer\b",
    r"\bencerr(?:o|amos|ando)\s+(?:a\s+)?(?:ligacao|chamada|atendimento)\b",
)


def _normalize(text: str) -> str:
    lowered = (text or "").lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _matches_any(normalized: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pat, normalized) for pat in patterns)


def agent_response_is_question(text: str) -> bool:
    """Trava dura: qualquer '?' na resposta => conversa continua."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return "?" in cleaned


def agent_response_is_farewell(text: str) -> bool:
    """Despedida clara do agente — exclui cortesia ambígua no meio da conversa."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    normalized = _normalize(cleaned)
    if normalized == _normalize(VOICE_FAREWELL_PHRASE):
        return True
    return _matches_any(normalized, _AGENT_FAREWELL_PATTERNS)


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


def user_signals_farewell(state: AgentState) -> bool:
    """
    Sinal de encerramento vem do TRANSCRIPT do usuário (última fala), não da resposta do agente.
    """
    message = (state.get("message") or "").strip()
    if matches_farewell_heuristic(message):
        return True

    call_sid = (state.get("twilio_call_sid") or "").strip()
    if call_sid and get_wrap_up_pending(call_sid):
        if matches_wrap_up_decline(message):
            return True

    return False


def detect_user_farewell_signal(state: AgentState) -> dict:
    """
    Fase 1 (pré-LLM): marca que o usuário sinalizou fim — sem should_hangup ainda.
    """
    if not _is_voice_channel(state.get("channel", "")):
        return {}
    if state.get("should_escalate"):
        return {}
    if _booking_consumed_turn(state):
        return {}

    if not user_signals_farewell(state):
        return {}

    call_sid = (state.get("twilio_call_sid") or "").strip()
    if call_sid:
        clear_wrap_up_pending(call_sid)

    return {"user_farewell_signal": True}


def _has_prior_dialogue(state: AgentState) -> bool:
    """
    True when at least one user/assistant turn completed before the current message.

    ``conversation_history`` is loaded from Redis in ``identify_intent`` (chat:{call_sid}
    for voice) and excludes the in-flight user message — empty means first turn of the call.
    """
    history = state.get("conversation_history") or []
    return len(history) > 0


def apply_hangup_decision(state: AgentState) -> dict:
    """
    Fase 2 (pós-LLM): hangup só com dupla confirmação:
      (a) usuário sinalizou encerramento no transcript
      (b) resposta do agente é despedida inequívoca (não pergunta, não cortesia solta)
    """
    if not _is_voice_channel(state.get("channel", "")):
        return {"should_hangup": False}

    if not state.get("user_farewell_signal"):
        return {"should_hangup": False}

    if not _has_prior_dialogue(state):
        return {"should_hangup": False}

    response = (state.get("response") or "").strip()

    if agent_response_is_question(response):
        return {"should_hangup": False}

    if not agent_response_is_farewell(response):
        return {"should_hangup": False}

    return {"should_hangup": True, "response": response}


def process_farewell_turn(state: AgentState) -> dict:
    """Compat: fase 1 apenas (grafo chama apply_hangup_decision depois do LLM)."""
    return detect_user_farewell_signal(state)
