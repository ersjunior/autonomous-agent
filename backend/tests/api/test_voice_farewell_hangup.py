"""API tests — turn-ready com should_hangup (Play + Hangup)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.services.voice_call_finalize import VOICE_FAREWELL_ORIGEM
from app.services.voice_turn_state import create_pending_turn, mark_turn_ready

pytestmark = pytest.mark.api

FAKE_MP3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    monkeypatch.setattr(settings, "voice_silence_close_seconds", 15)
    monkeypatch.setattr(settings, "voice_turn_max_poll_attempts", 60)
    monkeypatch.setattr(settings, "voice_turn_poll_pause_seconds", 1)


@pytest.mark.asyncio
async def test_turn_ready_hangup_returns_hangup_twiml(client) -> None:
    sid = "CA-hangup-farewell"
    tid = "turn-hangup-1"
    create_pending_turn(
        call_sid=sid,
        turn_id=tid,
        recording_url="https://rec",
        from_number="+5511999999999",
    )
    mark_turn_ready(sid, tid, audio_filename=FAKE_MP3, should_hangup=True)

    with (
        patch(
            "app.services.voice_call_finalize.finalize_voice_call_terminal",
            new=AsyncMock(return_value=True),
        ) as finalize,
        patch("app.services.voice_call_state.clear_voice_call_state") as clear_state,
    ):
        response = await client.post(
            f"/api/v1/channels/webhooks/voice/inbound/turn-ready"
            f"?call_sid={sid}&turn_id={tid}",
        )

    assert response.status_code == 200
    body = response.text
    assert FAKE_MP3 in body
    assert "<Hangup" in body
    assert "<Record" not in body
    finalize.assert_awaited_once()
    assert finalize.await_args.kwargs["origem"] == VOICE_FAREWELL_ORIGEM
    clear_state.assert_called_once_with(sid)


@pytest.mark.asyncio
async def test_turn_ready_without_hangup_keeps_record(client) -> None:
    sid = "CA-normal-turn"
    tid = "turn-normal-1"
    create_pending_turn(
        call_sid=sid,
        turn_id=tid,
        recording_url="https://rec",
        from_number="+5511999999999",
    )
    mark_turn_ready(sid, tid, audio_filename=FAKE_MP3, should_hangup=False)

    response = await client.post(
        f"/api/v1/channels/webhooks/voice/inbound/turn-ready"
        f"?call_sid={sid}&turn_id={tid}",
    )

    assert response.status_code == 200
    assert "<Record" in response.text
    assert "<Hangup" not in response.text
