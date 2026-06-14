"""Unit tests — cap de tokens e corte por frase para respostas em voz."""

from __future__ import annotations

import pytest

from agents.workers.response_agent import (
    _resolve_max_tokens,
    trim_voice_response_to_complete_sentence,
)
from app.core.config import settings

pytestmark = pytest.mark.unit


def test_trim_voice_response_keeps_complete_sentence() -> None:
    text = "Oferecemos atendimento por voz e WhatsApp. Horário: 9h às 18h."
    assert trim_voice_response_to_complete_sentence(text) == text


def test_trim_voice_response_cuts_incomplete_tail() -> None:
    text = "Primeira frase ok. Segunda frase ok. Terceira frase cort"
    assert trim_voice_response_to_complete_sentence(text) == "Primeira frase ok. Segunda frase ok."


def test_trim_voice_response_no_punctuation_unchanged() -> None:
    text = "Resposta sem pontuacao final"
    assert trim_voice_response_to_complete_sentence(text) == text


def test_resolve_max_tokens_voice_uses_voice_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 120)
    monkeypatch.setattr(settings, "response_max_tokens", 0)
    assert _resolve_max_tokens("voice") == 120


def test_resolve_max_tokens_whatsapp_uses_global_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 120)
    monkeypatch.setattr(settings, "response_max_tokens", 512)
    assert _resolve_max_tokens("whatsapp") == 512


def test_resolve_max_tokens_whatsapp_unlimited_when_zero(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 120)
    monkeypatch.setattr(settings, "response_max_tokens", 0)
    assert _resolve_max_tokens("telegram") is None
