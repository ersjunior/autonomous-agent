"""API tests — silêncio e StatusCallback na voz inbound."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.core.voice_silence_text import (
    VOICE_SILENCE_CLOSE_MESSAGE,
    VOICE_SILENCE_WARNING_MESSAGE,
)

pytestmark = pytest.mark.api

RECORD_CALLBACK = "/api/v1/channels/webhooks/voice/inbound/record-callback"
STATUS_CALLBACK = "/api/v1/channels/webhooks/voice/inbound/status"
FAKE_RECORDING_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/RE123"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_silence_warning_seconds", 30)
    monkeypatch.setattr(settings, "voice_silence_close_seconds", 15)


async def test_first_silence_returns_warning_and_record_timeout_15(client) -> None:
    with (
        patch(
            "app.services.voice_call_state.get_silence_stage",
            return_value=0,
        ),
        patch("app.services.voice_call_state.set_voice_call_state") as set_state,
        patch(
            "app.api.v1.channels._build_spoken_twiml_with_record",
            new=AsyncMock(return_value="<Response><Say>warn</Say><Record timeout=\"15\"/></Response>"),
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
    )
    assert 'timeout="15"' in response.text


async def test_second_silence_returns_hangup_and_finalizes(client) -> None:
    with (
        patch(
            "app.services.voice_call_state.get_silence_stage",
            return_value=1,
        ),
        patch(
            "app.services.voice_call_finalize.finalize_voice_call_terminal",
            new=AsyncMock(return_value=True),
        ) as finalize,
        patch("app.services.voice_call_state.clear_voice_call_state") as clear_state,
        patch(
            "app.api.v1.channels._build_voice_hangup_twiml_from_text",
            new=AsyncMock(
                return_value=f"<Response><Say>{VOICE_SILENCE_CLOSE_MESSAGE}</Say><Hangup/></Response>"
            ),
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
    finalize.assert_awaited_once()
    clear_state.assert_called_once_with("CA-silence-2")


async def test_valid_transcript_resets_silence_stage(client) -> None:
    fake_mp3 = "cccccccc-cccc-cccc-cccc-cccccccccccc.mp3"

    with (
        patch(
            "agents.channels.voice.twilio_voice_client.download_recording",
            new=AsyncMock(return_value=b"RIFFwav"),
        ),
        patch(
            "agents.channels.voice.tts_stt.speech_to_text",
            new=AsyncMock(return_value="Quero informações"),
        ),
        patch(
            "app.api.v1.channels._run_voice_agent_turn",
            new=AsyncMock(return_value="Claro, posso ajudar."),
        ),
        patch(
            "app.services.voice_audio.gerar_audio_chamada",
            new=AsyncMock(return_value=fake_mp3),
        ),
        patch("app.services.voice_call_state.reset_silence_stage") as reset_stage,
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
    reset_stage.assert_called_once_with("CA-speech", from_number="+5511999999999")
    assert fake_mp3 in response.text
    assert 'timeout="30"' in response.text


async def test_empty_transcript_counts_as_silence(client) -> None:
    with (
        patch(
            "agents.channels.voice.twilio_voice_client.download_recording",
            new=AsyncMock(return_value=b"RIFFwav"),
        ),
        patch(
            "agents.channels.voice.tts_stt.speech_to_text",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "app.api.v1.channels._handle_voice_silence_turn",
            new=AsyncMock(return_value=f"<Response><Say>{VOICE_SILENCE_WARNING_MESSAGE}</Say></Response>"),
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
    silence_handler.assert_awaited_once()


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
