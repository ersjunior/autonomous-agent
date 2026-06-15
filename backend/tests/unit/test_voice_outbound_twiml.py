"""Unit tests — TwiML outbound de voz (mensagem ativa + <Record>)."""

from __future__ import annotations

import pytest

from app.api.v1.channels import (
    _build_voice_outbound_play_twiml,
    _build_voice_outbound_say_twiml,
    _build_voice_say_only_twiml,
)
from app.core.config import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _public_base(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)


def test_outbound_play_twiml_includes_record_after_speech() -> None:
    filename = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"
    twiml = _build_voice_outbound_play_twiml(filename)
    assert "<Play>https://example.com/api/v1/channels/webhooks/voice/audio/" in twiml
    assert "record-callback" in twiml
    assert "<Record" in twiml
    assert 'timeout="30"' in twiml
    assert "<Hangup" not in twiml


def test_outbound_say_twiml_includes_record_after_speech() -> None:
    twiml = _build_voice_outbound_say_twiml("Olá, mensagem ativa de teste.")
    assert "Polly.Camila" in twiml
    assert "Olá, mensagem ativa de teste." in twiml
    assert "record-callback" in twiml
    assert "<Record" in twiml
    assert 'timeout="30"' in twiml
    assert "<Hangup" not in twiml


def test_say_only_twiml_has_no_record() -> None:
    twiml = _build_voice_say_only_twiml("Modo indisponível.")
    assert "Modo indisponível." in twiml
    assert "<Record" not in twiml
