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
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)
    monkeypatch.setattr(settings, "voice_record_max_length_sec", 30)


def test_outbound_play_twiml_includes_record_after_speech() -> None:
    filename = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"
    twiml = _build_voice_outbound_play_twiml(filename)
    assert filename in twiml
    assert "<Record" in twiml
    assert 'timeout="2"' in twiml


def test_outbound_say_twiml_includes_record_after_speech() -> None:
    twiml = _build_voice_outbound_say_twiml("Mensagem ativa")
    assert "Mensagem ativa" in twiml
    assert "<Record" in twiml
    assert 'timeout="2"' in twiml


def test_say_only_twiml_has_no_record() -> None:
    twiml = _build_voice_say_only_twiml("Apenas fala")
    assert "Apenas fala" in twiml
    assert "<Record" not in twiml
