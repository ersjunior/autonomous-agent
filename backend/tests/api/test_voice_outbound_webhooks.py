"""API tests — webhooks outbound de voz (TwiML com <Record>)."""

from __future__ import annotations

import pytest

from app.core.config import settings

pytestmark = pytest.mark.api

FAKE_MP3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)


async def test_outbound_audio_webhook_returns_play_and_record(client) -> None:
    response = await client.get(
        f"/api/v1/channels/webhooks/voice/outbound-audio?audio={FAKE_MP3}",
    )

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/xml")
    body = response.text
    assert FAKE_MP3 in body
    assert "<Play>" in body
    assert "<Record" in body
    assert 'timeout="2"' in body
    assert "record-callback" in body
    assert "<Hangup" not in body


async def test_outbound_say_webhook_returns_say_and_record(client) -> None:
    response = await client.get(
        "/api/v1/channels/webhooks/voice/outbound?text=Ol%C3%A1%20teste",
    )

    assert response.status_code == 200
    body = response.text
    assert "Polly.Camila" in body
    assert "<Record" in body
    assert "record-callback" in body
