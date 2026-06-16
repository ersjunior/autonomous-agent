"""Unit tests — helpers TwiML de voz (timeout dinâmico)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.v1.channels import (
    _build_spoken_twiml_with_record,
    _build_voice_hangup_twiml,
    _build_voice_record_only_twiml,
    _build_voice_turn_twiml,
    _handle_voice_silence_turn,
    _is_voice_silence,
    _voice_record_block_xml,
    _voice_silence_reason,
)
from app.core.config import settings
from app.core.voice_silence_text import VOICE_SILENCE_CLOSE_MESSAGE

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _voice_record_settings(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)
    monkeypatch.setattr(settings, "voice_record_max_length_sec", 30)
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    monkeypatch.setattr(settings, "voice_silence_close_seconds", 15)


def test_voice_record_block_xml_uses_short_silence_timeout_by_default() -> None:
    xml = _voice_record_block_xml()
    assert 'timeout="2"' in xml
    assert 'maxLength="30"' in xml
    assert 'playBeep="false"' in xml


def test_voice_record_block_xml_accepts_explicit_timeout() -> None:
    xml = _voice_record_block_xml(record_timeout_sec=5)
    assert 'timeout="5"' in xml


def test_build_voice_turn_twiml_passes_record_timeout() -> None:
    twiml = _build_voice_turn_twiml(
        VOICE_SILENCE_CLOSE_MESSAGE,
        is_fallback=True,
        record_timeout_sec=5,
    )
    assert VOICE_SILENCE_CLOSE_MESSAGE in twiml
    assert 'timeout="5"' in twiml


def test_build_voice_hangup_twiml_includes_hangup() -> None:
    twiml = _build_voice_hangup_twiml(VOICE_SILENCE_CLOSE_MESSAGE, is_fallback=True)
    assert "<Hangup" in twiml
    assert VOICE_SILENCE_CLOSE_MESSAGE in twiml


def test_is_voice_silence_detects_empty_url_and_short_duration() -> None:
    assert _is_voice_silence("", 0.0) is True
    assert _is_voice_silence("https://rec", 0.5) is True
    assert _is_voice_silence("https://rec", 2.0, "") is True
    assert _is_voice_silence("https://rec", 2.0, "olá") is False
    assert _voice_silence_reason("https://rec", 4.0) is None


def test_build_spoken_twiml_uses_cached_phrase_play(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.channels.get_phrase_audio_filename",
        lambda text: "voice_phrase_aabbccddeeff0011.mp3",
    )
    twiml = _build_spoken_twiml_with_record(VOICE_SILENCE_CLOSE_MESSAGE)
    assert "voice_phrase_aabbccddeeff0011.mp3" in twiml
    assert "<Play>" in twiml
    assert "<Say" not in twiml
    assert 'timeout="2"' in twiml


def test_build_spoken_twiml_falls_back_to_polly_when_cache_miss(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.channels.get_phrase_audio_filename",
        lambda text: None,
    )
    twiml = _build_spoken_twiml_with_record("Teste fallback")
    assert "<Say" in twiml
    assert "Teste fallback" in twiml


def test_record_only_twiml_has_record_without_speech() -> None:
    twiml = _build_voice_record_only_twiml()
    assert "<Record" in twiml
    assert "<Play" not in twiml
    assert "<Say" not in twiml
    assert 'timeout="2"' in twiml


@pytest.mark.asyncio
async def test_handle_silence_partial_returns_record_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.voice_call_state.add_accumulated_silence",
        lambda *a, **k: 6.0,
    )
    monkeypatch.setattr("app.services.voice_call_state.get_silence_stage", lambda _: 0)
    twiml = await _handle_voice_silence_turn(
        call_sid="CA-partial",
        from_number="+5511999999999",
    )
    assert "<Record" in twiml
    assert "<Hangup" not in twiml


@pytest.mark.asyncio
async def test_handle_silence_warning_when_accumulated_reaches_threshold(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.voice_call_state.add_accumulated_silence",
        lambda *a, **k: 30.0,
    )
    monkeypatch.setattr("app.services.voice_call_state.get_silence_stage", lambda _: 0)
    monkeypatch.setattr("app.services.voice_call_state.set_voice_call_state", MagicMock())
    monkeypatch.setattr(
        "app.api.v1.channels.get_phrase_audio_filename",
        lambda text: "voice_phrase_aabbccddeeff0011.mp3",
    )
    twiml = await _handle_voice_silence_turn(
        call_sid="CA-warn",
        from_number="+5511999999999",
    )
    assert "voice_phrase_aabbccddeeff0011.mp3" in twiml
    assert "<Hangup" not in twiml
