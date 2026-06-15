"""Unit tests — helpers TwiML de voz (timeout dinâmico)."""

from __future__ import annotations

import pytest

from app.api.v1.channels import (
    _build_voice_hangup_twiml,
    _build_voice_turn_twiml,
    _is_voice_silence,
    _voice_record_block_xml,
)
from app.core.config import settings
from app.core.voice_silence_text import VOICE_SILENCE_CLOSE_MESSAGE

pytestmark = pytest.mark.unit


def test_voice_record_block_xml_uses_warning_timeout_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    xml = _voice_record_block_xml()
    assert 'timeout="30"' in xml
    assert 'maxLength="30"' in xml
    assert 'playBeep="false"' in xml


def test_voice_record_block_xml_accepts_close_timeout(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    xml = _voice_record_block_xml(record_timeout_sec=15)
    assert 'timeout="15"' in xml


def test_build_voice_turn_twiml_passes_record_timeout(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    twiml = _build_voice_turn_twiml(
        VOICE_SILENCE_CLOSE_MESSAGE,
        is_fallback=True,
        record_timeout_sec=15,
    )
    assert VOICE_SILENCE_CLOSE_MESSAGE in twiml
    assert 'timeout="15"' in twiml


def test_build_voice_hangup_twiml_includes_hangup(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    twiml = _build_voice_hangup_twiml(VOICE_SILENCE_CLOSE_MESSAGE, is_fallback=True)
    assert "<Hangup" in twiml
    assert VOICE_SILENCE_CLOSE_MESSAGE in twiml


def test_is_voice_silence_detects_empty_url_and_short_duration() -> None:
    assert _is_voice_silence("", 0.0) is True
    assert _is_voice_silence("https://rec", 0.5) is True
    assert _is_voice_silence("https://rec", 2.0, "") is True
    assert _is_voice_silence("https://rec", 2.0, "olá") is False
