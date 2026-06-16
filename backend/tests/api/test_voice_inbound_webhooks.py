"""API tests — webhooks inbound de voz (record-callback simulado)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.voice_silence_text import VOICE_SILENCE_WARNING_MESSAGE

pytestmark = pytest.mark.api

RECORD_CALLBACK = "/api/v1/channels/webhooks/voice/inbound/record-callback"
TURN_READY = "/api/v1/channels/webhooks/voice/inbound/turn-ready"
FAKE_RECORDING_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/RE123"
FAKE_MP3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    monkeypatch.setattr(settings, "voice_silence_close_seconds", 15)
    monkeypatch.setattr(settings, "voice_turn_max_poll_attempts", 60)
    monkeypatch.setattr(settings, "voice_turn_poll_pause_seconds", 1)


async def test_record_callback_empty_recording_triggers_silence_flow(client) -> None:
    with patch(
        "app.api.v1.channels._handle_voice_silence_turn",
        new=AsyncMock(
            return_value=f"<Response><Say>{VOICE_SILENCE_WARNING_MESSAGE}</Say><Record/></Response>"
        ),
    ) as silence_handler:
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CAtest",
                "From": "+5511999999999",
                "RecordingUrl": "",
                "RecordingDuration": "0",
            },
        )

    assert response.status_code == 200
    silence_handler.assert_awaited_once()
    assert VOICE_SILENCE_WARNING_MESSAGE in response.text


async def test_record_callback_silence_short_duration_triggers_silence_flow(client) -> None:
    with patch(
        "app.api.v1.channels._handle_voice_silence_turn",
        new=AsyncMock(
            return_value=f"<Response><Say>{VOICE_SILENCE_WARNING_MESSAGE}</Say><Record/></Response>"
        ),
    ) as silence_handler:
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CAtest",
                "From": "+5511999999999",
                "RecordingUrl": FAKE_RECORDING_URL,
                "RecordingDuration": "0",
            },
        )

    assert response.status_code == 200
    silence_handler.assert_awaited_once()
    assert VOICE_SILENCE_WARNING_MESSAGE in response.text


async def test_record_callback_dispatches_async_turn(client) -> None:
    enqueue_mock = AsyncMock()

    with patch(
        "app.api.v1.channels._enqueue_voice_inbound_turn",
        enqueue_mock,
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CAtest",
                "From": "+5511999999999",
                "RecordingUrl": FAKE_RECORDING_URL,
                "RecordingDuration": "4",
            },
        )

    assert response.status_code == 200
    body = response.text
    assert "<Redirect" in body
    assert "turn-ready" in body
    assert "<Play" not in body
    assert "<Say" not in body
    assert "<Record" not in body
    enqueue_mock.assert_awaited_once()
    call_kwargs = enqueue_mock.await_args.kwargs
    assert call_kwargs["call_sid"] == "CAtest"
    assert call_kwargs["recording_url"] == FAKE_RECORDING_URL
    assert call_kwargs["from_number"] == "+5511999999999"


async def test_record_callback_redirect_only_no_blocking_wait(client) -> None:
    with patch(
        "app.api.v1.channels._enqueue_voice_inbound_turn",
        new=AsyncMock(),
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CAasync",
                "From": "+5511999999999",
                "RecordingUrl": FAKE_RECORDING_URL,
                "RecordingDuration": "5",
            },
        )

    assert response.status_code == 200
    assert "turn-ready" in response.text
    assert "<Play" not in response.text


async def test_turn_ready_pending_returns_pause_and_redirect(client) -> None:
    with (
        patch(
            "app.api.v1.channels.get_voice_turn",
            return_value={"status": "pending", "poll_count": 0},
        ),
        patch("app.api.v1.channels.increment_turn_poll_count", return_value=1),
    ):
        response = await client.post(
            f"{TURN_READY}?call_sid=CAtest&turn_id=turn-1",
        )

    assert response.status_code == 200
    body = response.text
    assert '<Pause length="1"/>' in body
    assert "<Redirect" in body
    assert "turn-ready" in body
    assert "<Play" not in body


async def test_turn_ready_ready_logs_delivery(client) -> None:
    with (
        patch(
            "app.api.v1.channels.get_voice_turn",
            return_value={
                "status": "ready",
                "audio_filename": FAKE_MP3,
                "created_at": "2026-06-15T12:00:00+00:00",
                "poll_count": 3,
            },
        ),
        patch("app.api.v1.channels.mark_turn_consumed"),
        patch("app.api.v1.channels.logger") as log_mock,
    ):
        response = await client.post(
            f"{TURN_READY}?call_sid=CAtest&turn_id=turn-delivered",
        )

    assert response.status_code == 200
    assert FAKE_MP3 in response.text
    delivered_logs = [
        c for c in log_mock.info.call_args_list
        if c.args and c.args[0] == "Voice turn delivered call_sid=%s turn_id=%s wait_total_ms=%s poll_attempts=%s audio=%s"
    ]
    assert len(delivered_logs) == 1
    assert delivered_logs[0].args[4] == 3
    assert delivered_logs[0].args[3] != "?"


async def test_turn_ready_ready_returns_play_and_record(client) -> None:
    with (
        patch(
            "app.api.v1.channels.get_voice_turn",
            return_value={
                "status": "ready",
                "audio_filename": FAKE_MP3,
            },
        ),
        patch("app.api.v1.channels.mark_turn_consumed") as consumed,
    ):
        response = await client.post(
            f"{TURN_READY}?call_sid=CAtest&turn_id=turn-2",
        )

    assert response.status_code == 200
    body = response.text
    assert FAKE_MP3 in body
    assert "<Play>" in body
    assert "<Record" in body
    assert "record-callback" in body
    consumed.assert_called_once_with("CAtest", "turn-2")


async def test_turn_ready_error_returns_say_and_record(client) -> None:
    with (
        patch(
            "app.api.v1.channels.get_voice_turn",
            return_value={"status": "error", "error": "boom"},
        ),
        patch("app.api.v1.channels.mark_turn_consumed"),
    ):
        response = await client.post(
            f"{TURN_READY}?call_sid=CAtest&turn_id=turn-3",
        )

    assert response.status_code == 200
    assert "<Say" in response.text
    assert "<Record" in response.text


async def test_turn_ready_poll_limit_returns_timeout_message(client) -> None:
    with (
        patch(
            "app.api.v1.channels.get_voice_turn",
            return_value={"status": "pending"},
        ),
        patch(
            "app.api.v1.channels.increment_turn_poll_count",
            return_value=60,
        ),
        patch("app.api.v1.channels.mark_turn_error"),
        patch("app.api.v1.channels.mark_turn_consumed"),
    ):
        response = await client.post(
            f"{TURN_READY}?call_sid=CAtest&turn_id=turn-4",
        )

    assert response.status_code == 200
    assert "demorando" in response.text.lower() or "Desculpe" in response.text
