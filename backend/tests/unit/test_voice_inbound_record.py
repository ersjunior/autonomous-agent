"""Unit tests — inbound de voz (record-callback helpers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agents.channels.voice.twilio_voice_client import download_recording
from app.api.v1.channels import (
    _build_voice_turn_twiml,
    _parse_recording_duration,
    _voice_record_block_xml,
)
from app.core.config import settings

pytestmark = pytest.mark.unit


def test_parse_recording_duration() -> None:
    assert _parse_recording_duration("3.5") == 3.5
    assert _parse_recording_duration("") == 0.0
    assert _parse_recording_duration("invalid") == 0.0


def test_build_voice_turn_twiml_play_and_record(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    twiml = _build_voice_turn_twiml(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3",
        is_fallback=False,
    )
    assert "<Play>https://example.com/api/v1/channels/webhooks/voice/audio/" in twiml
    assert "record-callback" in twiml
    assert "<Record" in twiml
    assert 'timeout="30"' in twiml


def test_build_voice_turn_twiml_say_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    twiml = _build_voice_turn_twiml("Teste de fallback", is_fallback=True)
    assert "Polly.Camila" in twiml
    assert "Teste de fallback" in twiml
    assert "<Record" in twiml
    assert 'timeout="30"' in twiml


def test_voice_record_block_xml_timeout(monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    assert 'timeout="30"' in _voice_record_block_xml()
    assert 'timeout="15"' in _voice_record_block_xml(record_timeout_sec=15)


@pytest.mark.asyncio
async def test_download_recording_retries_404_then_raises(monkeypatch) -> None:
    monkeypatch.setattr(settings, "twilio_account_sid", "ACtest")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret")
    calls = {"n": 0}

    async def fake_get(self, url, **kwargs):
        calls["n"] += 1
        request = httpx.Request("GET", url)
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agents.channels.voice.twilio_voice_client.asyncio.sleep",
        AsyncMock(),
    )

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(httpx.HTTPStatusError):
            await download_recording("https://api.twilio.com/rec/RE123")

    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_download_recording_success_after_404(monkeypatch) -> None:
    monkeypatch.setattr(settings, "twilio_account_sid", "ACtest")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret")
    calls = {"n": 0}

    async def fake_get(self, url, **kwargs):
        calls["n"] += 1
        request = httpx.Request("GET", url)
        if calls["n"] < 2:
            return httpx.Response(404, request=request)
        return httpx.Response(200, content=b"RIFFfake", request=request)

    monkeypatch.setattr(
        "agents.channels.voice.twilio_voice_client.asyncio.sleep",
        AsyncMock(),
    )

    with patch("httpx.AsyncClient.get", new=fake_get):
        data = await download_recording("https://api.twilio.com/rec/RE123")

    assert data == b"RIFFfake"
    assert calls["n"] == 2
