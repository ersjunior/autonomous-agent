"""API tests — silêncio e StatusCallback na voz inbound."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.core.voice_silence_text import VOICE_SILENCE_WARNING_MESSAGE

pytestmark = pytest.mark.api

RECORD_CALLBACK = "/api/v1/channels/webhooks/voice/inbound/record-callback"
STATUS_CALLBACK = "/api/v1/channels/webhooks/voice/inbound/status"
FAKE_RECORDING_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/RE123"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_record_silence_timeout_sec", 2)
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    monkeypatch.setattr(settings, "voice_silence_close_seconds", 15)


async def test_partial_silence_reopens_record_without_warning(client) -> None:
    with (
        patch(
            "app.services.voice_call_state.add_accumulated_silence",
            return_value=6.0,
        ),
        patch("app.services.voice_call_state.get_silence_stage", return_value=0),
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CA-silence-partial",
                "From": "+5511999999999",
                "RecordingUrl": "",
                "RecordingDuration": "0",
            },
        )

    assert response.status_code == 200
    assert "<Record" in response.text
    assert 'timeout="2"' in response.text
    assert VOICE_SILENCE_WARNING_MESSAGE not in response.text
    assert "<Hangup" not in response.text


async def test_warning_after_accumulated_inactivity(client) -> None:
    with (
        patch(
            "app.services.voice_call_state.add_accumulated_silence",
            return_value=30.0,
        ),
        patch("app.services.voice_call_state.get_silence_stage", return_value=0),
        patch("app.services.voice_call_state.set_voice_call_state") as set_state,
        patch(
            "app.api.v1.channels.get_phrase_audio_filename",
            return_value="voice_phrase_aabbccddeeff0011.mp3",
        ),
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CA-silence-1",
                "From": "+5511999999999",
                "RecordingUrl": "",
                "RecordingDuration": "0",
            },
        )

    assert response.status_code == 200
    set_state.assert_called_once_with(
        "CA-silence-1",
        silence_stage=1,
        from_number="+5511999999999",
        accumulated_silence_sec=0.0,
    )
    assert 'timeout="2"' in response.text
    assert "voice_phrase_aabbccddeeff0011.mp3" in response.text


async def test_second_silence_returns_hangup_and_finalizes(client) -> None:
    with (
        patch(
            "app.services.voice_call_state.add_accumulated_silence",
            return_value=15.0,
        ),
        patch("app.services.voice_call_state.get_silence_stage", return_value=1),
        patch(
            "app.services.voice_call_finalize.finalize_voice_call_terminal",
            new=AsyncMock(return_value=True),
        ) as finalize,
        patch("app.services.voice_call_state.clear_voice_call_state") as clear_state,
        patch(
            "app.api.v1.channels.get_phrase_audio_filename",
            return_value="voice_phrase_aabbccddeeff0022.mp3",
        ),
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CA-silence-2",
                "From": "+5511999999999",
                "RecordingUrl": "",
                "RecordingDuration": "0",
            },
        )

    assert response.status_code == 200
    assert "<Hangup" in response.text
    assert "voice_phrase_aabbccddeeff0022.mp3" in response.text
    finalize.assert_awaited_once()
    clear_state.assert_called_once_with("CA-silence-2")


async def test_valid_transcript_dispatches_async_turn(client) -> None:
    enqueue_mock = AsyncMock()

    with patch(
        "app.api.v1.channels._enqueue_voice_inbound_turn",
        enqueue_mock,
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CA-speech",
                "From": "+5511999999999",
                "RecordingUrl": FAKE_RECORDING_URL,
                "RecordingDuration": "4",
            },
        )

    assert response.status_code == 200
    enqueue_mock.assert_awaited_once()
    assert "turn-ready" in response.text
    assert "<Play" not in response.text


async def test_empty_transcript_dispatched_to_worker_not_inline_silence(client) -> None:
    """STT vazio é detectado no worker; record-callback só enfileira."""
    with (
        patch(
            "app.api.v1.channels._enqueue_voice_inbound_turn",
            new=AsyncMock(),
        ),
        patch(
            "app.api.v1.channels._handle_voice_silence_turn",
            new=AsyncMock(),
        ) as silence_handler,
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CA-empty-stt",
                "From": "+5511999999999",
                "RecordingUrl": FAKE_RECORDING_URL,
                "RecordingDuration": "3",
            },
        )

    assert response.status_code == 200
    silence_handler.assert_not_awaited()


async def test_status_callback_completed_finalizes_when_not_terminal(client) -> None:
    with (
        patch(
            "app.services.voice_call_finalize.finalize_voice_call_terminal",
            new=AsyncMock(return_value=True),
        ) as finalize,
        patch("app.services.voice_call_state.clear_voice_call_state") as clear_state,
    ):
        response = await client.post(
            STATUS_CALLBACK,
            data={
                "CallSid": "CA-hangup",
                "CallStatus": "completed",
                "From": "+5511999999999",
            },
        )

    assert response.status_code == 204
    finalize.assert_awaited_once()
    clear_state.assert_called_once_with("CA-hangup")


async def test_status_callback_ignores_non_terminal_events(client) -> None:
    with patch(
        "app.services.voice_call_finalize.finalize_voice_call_terminal",
        new=AsyncMock(return_value=True),
    ) as finalize:
        response = await client.post(
            STATUS_CALLBACK,
            data={
                "CallSid": "CA-ringing",
                "CallStatus": "ringing",
                "From": "+5511999999999",
            },
        )

    assert response.status_code == 204
    finalize.assert_not_awaited()


async def test_status_callback_idempotent_when_already_terminal(client) -> None:
    with (
        patch(
            "app.services.voice_call_finalize.finalize_voice_call_terminal",
            new=AsyncMock(return_value=False),
        ) as finalize,
        patch("app.services.voice_call_state.clear_voice_call_state") as clear_state,
    ):
        response = await client.post(
            STATUS_CALLBACK,
            data={
                "CallSid": "CA-done",
                "CallStatus": "completed",
                "From": "+5511999999999",
            },
        )

    assert response.status_code == 204
    finalize.assert_awaited_once()
    clear_state.assert_called_once_with("CA-done")
