"""Unit tests — TwiML inbound de voz (<Record> timeout curto)."""

from __future__ import annotations

import pytest

from app.api.v1.channels import (
    _build_voice_inbound_twiml,
    _build_voice_turn_twiml,
    _voice_record_block_xml,
)
from app.core.config import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _voice_record_settings(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)
    monkeypatch.setattr(settings, "voice_record_max_length_sec", 30)


def test_inbound_twiml_uses_short_record_timeout() -> None:
    twiml = _build_voice_inbound_twiml("Olá", is_fallback=True)
    assert 'timeout="2"' in twiml
    assert 'maxLength="30"' in twiml


def test_turn_twiml_default_record_timeout() -> None:
    filename = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"
    twiml = _build_voice_turn_twiml(filename, is_fallback=False)
    assert 'timeout="2"' in twiml


def test_voice_record_block_xml_timeout() -> None:
    assert 'timeout="2"' in _voice_record_block_xml()
    assert 'timeout="5"' in _voice_record_block_xml(record_timeout_sec=5)
