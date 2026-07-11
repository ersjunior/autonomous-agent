"""Unit tests — sanitização de voz para TTS e limites de tokens do LLM."""

from __future__ import annotations

import pytest

from agents.workers.response_agent import (
    TEXT_BEHAVIOR_PROMPT,
    VOICE_BEHAVIOR_PROMPT,
    _resolve_max_tokens,
    cap_voice_response_at_sentence_boundary,
    sanitize_voice_response_for_telephony,
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


def test_sanitize_keeps_full_multi_sentence_reply(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    text = (
        "Entendi sua pergunta sobre custos. "
        "Posso verificar na base e te retorno em seguida. "
        "Também posso enviar por e-mail se preferir."
    )
    assert sanitize_voice_response_for_telephony(text) == text


def test_sanitize_keeps_long_natural_reply_under_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    text = (
        "Entendi perfeitamente sua solicitação sobre os custos detalhados "
        "do plano premium para o seu projeto acadêmico completo."
    )
    assert sanitize_voice_response_for_telephony(text) == text


def test_sanitize_strips_markdown(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    text = "**Olá!** Temos o plano *Premium* disponível."
    assert sanitize_voice_response_for_telephony(text) == "Olá! Temos o plano Premium disponível."


def test_sanitize_trims_incomplete_tail_only(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    text = "Primeira frase ok. Segunda incompleta cort"
    assert sanitize_voice_response_for_telephony(text) == "Primeira frase ok."


def test_sanitize_realistic_reply_under_300_chars_not_truncated(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    text = (
        "Entendi! Você quer saber sobre os custos e também está procurando por informações "
        "sobre design patterns para o seu projeto do TCC. Posso verificar as informações "
        "disponíveis sobre os cursos da Campanha Ativa e fornecer mais detalhes sobre os custos."
    )
    result = sanitize_voice_response_for_telephony(text)
    assert result == text
    assert "design patterns" in result


def test_cap_voice_response_cuts_at_sentence_boundary_not_mid_word() -> None:
    text = (
        "Primeira frase curta. Segunda frase também ok. "
        "Terceira frase longa que empurra o texto além do limite generoso de caracteres "
        "e não deveria ser falada inteira numa ligação telefônica breve."
    )
    capped = cap_voice_response_at_sentence_boundary(text, max_chars=120)
    assert capped.endswith(".")
    assert "Terceira" not in capped
    assert capped == "Primeira frase curta. Segunda frase também ok."


def test_cap_voice_response_extreme_prolix_reply(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    text = (
        "A ByteCell Academy oferece cursos em diversas áreas, incluindo Excel, "
        "Banco de Dados e BI. Eles também têm Marketing Digital, Gestão de Projetos "
        "e Comunicação Efetiva. As opções podem variar conforme a localização. "
        "Se quiser saber mais, entre em contato com a escola ou visite o site para "
        "obter informações detalhadas sobre todos os programas disponíveis hoje."
    )
    assert len(text) > 300
    result = sanitize_voice_response_for_telephony(text)
    assert len(result) <= 300
    assert result.endswith(".")
    assert "visite o site" not in result


def test_sanitize_skips_char_cap_when_zero(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 0)
    text = "Frase um. " + "Outra frase. " * 50
    assert sanitize_voice_response_for_telephony(text) == text.strip()


def test_resolve_max_tokens_voice_uses_voice_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 64)
    monkeypatch.setattr(settings, "response_max_tokens", 1024)
    assert _resolve_max_tokens("voice") == 64


def test_resolve_max_tokens_whatsapp_uses_global_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 64)
    monkeypatch.setattr(settings, "response_max_tokens", 1024)
    assert _resolve_max_tokens("whatsapp") == 1024


def test_resolve_max_tokens_whatsapp_unlimited_when_zero(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_response_max_tokens", 64)
    monkeypatch.setattr(settings, "response_max_tokens", 0)
    assert _resolve_max_tokens("telegram") is None


def test_voice_behavior_prompt_enforces_brevity() -> None:
    lowered = VOICE_BEHAVIOR_PROMPT.lower()
    assert "breve" in lowered
    assert "1 a 3 frases" in lowered
    assert "nunca liste" in lowered
    assert "detalhar" in lowered
    assert "telegráfico" in lowered
    assert "RAG" in VOICE_BEHAVIOR_PROMPT


def test_text_behavior_prompt_allows_developed_replies() -> None:
    assert "desenvolver" in TEXT_BEHAVIOR_PROMPT.lower()
    assert "prolix" not in TEXT_BEHAVIOR_PROMPT.lower()
