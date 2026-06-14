"""API tests — webhooks inbound de voz (record-callback simulado)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.channels import VOICE_REPEAT_MESSAGE
from app.core.config import settings

pytestmark = pytest.mark.api

RECORD_CALLBACK = "/api/v1/channels/webhooks/voice/inbound/record-callback"
FAKE_RECORDING_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/RE123"
FAKE_TRANSCRIPT = "Quais serviços vocês oferecem?"
FAKE_AGENT_REPLY = "Oferecemos atendimento automatizado por voz, WhatsApp e Telegram."
FAKE_MP3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")


async def test_record_callback_empty_recording_returns_repeat_twiml(client) -> None:
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
    assert response.headers.get("content-type", "").startswith("application/xml")
    body = response.text
    assert "Não entendi" in body
    assert "<Record" in body
    assert "record-callback" in body


async def test_record_callback_silence_short_duration_returns_repeat_twiml(client) -> None:
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
    assert response.headers.get("content-type", "").startswith("application/xml")
    body = response.text
    assert VOICE_REPEAT_MESSAGE in body
    assert "<Say" in body
    assert "<Record" in body
    assert "record-callback" in body


async def test_record_callback_agent_turn_mocked(client) -> None:
    fake_mp3 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.mp3"

    with (
        patch(
            "agents.channels.voice.twilio_voice_client.download_recording",
            new=AsyncMock(return_value=b"RIFFwav"),
        ),
        patch(
            "agents.channels.voice.tts_stt.speech_to_text",
            new=AsyncMock(return_value="Quero saber o horário de funcionamento"),
        ),
        patch(
            "app.api.v1.channels._run_voice_agent_turn",
            new=AsyncMock(return_value="Funcionamos das nove às dezoito horas."),
        ),
        patch(
            "app.services.voice_audio.gerar_audio_chamada",
            new=AsyncMock(return_value=fake_mp3),
        ),
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
    assert response.headers.get("content-type", "").startswith("application/xml")
    body = response.text
    assert fake_mp3 in body
    assert "<Play>" in body
    assert "<Record" in body
    assert "record-callback" in body
    assert "Funcionamos" not in body  # resposta via Play URL, não Say inline


async def test_record_callback_full_turn_mocked_without_gpu(client) -> None:
    """Turno completo mockado — valida STT→agente→TTS no callback sem GPU/Ollama/Coqui."""
    with (
        patch(
            "agents.channels.voice.twilio_voice_client.download_recording",
            new=AsyncMock(return_value=b"RIFFfake"),
        ),
        patch(
            "agents.channels.voice.tts_stt.speech_to_text",
            new=AsyncMock(return_value=FAKE_TRANSCRIPT),
        ),
        patch(
            "app.api.v1.channels._run_voice_agent_turn",
            new=AsyncMock(return_value=FAKE_AGENT_REPLY),
        ),
        patch(
            "app.services.voice_audio.gerar_audio_chamada",
            new=AsyncMock(return_value=FAKE_MP3),
        ),
    ):
        response = await client.post(
            RECORD_CALLBACK,
            data={
                "CallSid": "CAtestfull",
                "From": "+5511948660628",
                "To": "+5511888888888",
                "RecordingUrl": FAKE_RECORDING_URL,
                "RecordingDuration": "3",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/xml")
    body = response.text
    assert FAKE_MP3 in body
    assert "<Play>" in body
    assert "<Record" in body
    assert "record-callback" in body
    assert FAKE_AGENT_REPLY not in body
