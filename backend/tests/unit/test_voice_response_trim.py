"""Unit tests — cap de tokens e corte por frase para respostas em voz."""

from __future__ import annotations

import pytest

from agents.workers.response_agent import (
    VOICE_MAX_RESPONSE_CHARS,
    _resolve_max_tokens,
    cap_voice_response_for_telephony,
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


def test_cap_voice_response_keeps_one_short_sentence() -> None:
    text = "Claro, posso ajudar com os custos."
    assert cap_voice_response_for_telephony(text) == text


def test_cap_voice_response_limits_to_one_sentence() -> None:
    text = (
        "Entendi sua pergunta sobre custos. "
        "Posso verificar na base e te retorno em seguida. "
        "Também posso enviar por e-mail se preferir."
    )
    result = cap_voice_response_for_telephony(text)
    assert result == "Entendi sua pergunta sobre custos."
    assert "Posso verificar" not in result


def test_cap_voice_response_truncates_long_sentence_at_word_boundary() -> None:
    text = (
        "Entendi perfeitamente sua solicitação sobre os custos detalhados "
        "do plano premium para o seu projeto acadêmico completo."
    )
    result = cap_voice_response_for_telephony(text)
    assert len(result) <= VOICE_MAX_RESPONSE_CHARS
    assert not result.endswith(" acad")
    assert result.endswith(".")


def test_cap_voice_response_drops_to_one_sentence_when_over_char_limit() -> None:
    first = "A" * (VOICE_MAX_RESPONSE_CHARS - 1) + "."
    second = "Segunda frase curta."
    text = f"{first} {second}"
    result = cap_voice_response_for_telephony(text)
    assert result == first


def test_cap_voice_response_realistic_long_reply() -> None:
    text = (
        "Entendi! Você quer saber sobre os custos e também está procurando por informações "
        "sobre design patterns para o seu projeto do TCC. Posso verificar as informações "
        "disponíveis sobre os cursos da Campanha Ativa e fornecer mais detalhes sobre os custos."
    )
    result = cap_voice_response_for_telephony(text)
    assert result == "Entendi!"
    assert len(result) <= VOICE_MAX_RESPONSE_CHARS


def test_resolve_max_tokens_voice_uses_voice_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 35)
    monkeypatch.setattr(settings, "response_max_tokens", 0)
    assert _resolve_max_tokens("voice") == 35


def test_resolve_max_tokens_whatsapp_uses_global_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 35)
    monkeypatch.setattr(settings, "response_max_tokens", 512)
    assert _resolve_max_tokens("whatsapp") == 512


def test_resolve_max_tokens_whatsapp_unlimited_when_zero(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 35)
    monkeypatch.setattr(settings, "response_max_tokens", 0)
    assert _resolve_max_tokens("telegram") is None
