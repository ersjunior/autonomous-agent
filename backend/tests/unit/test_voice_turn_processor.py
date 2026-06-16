"""Unit tests — processamento assíncrono de turno de voz (worker)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.voice_turn_processor import process_voice_inbound_turn

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_process_turn_marks_ready(monkeypatch) -> None:
    with (
        patch(
            "app.services.voice_turn_processor.download_recording",
            new=AsyncMock(return_value=b"RIFFwav"),
        ),
        patch(
            "app.services.voice_turn_processor.speech_to_text",
            new=AsyncMock(return_value="Olá, preciso de ajuda"),
        ),
        patch(
            "app.services.voice_turn_processor.run_voice_agent_turn",
            new=AsyncMock(return_value="Posso ajudar sim."),
        ),
        patch(
            "app.services.voice_turn_processor.gerar_audio_chamada",
            new=AsyncMock(return_value="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"),
        ),
        patch("app.services.voice_turn_processor.reset_silence_stage") as reset,
        patch("app.services.voice_turn_processor.mark_turn_ready") as mark_ready,
    ):
        await process_voice_inbound_turn(
            call_sid="CAworker",
            turn_id="tw1",
            recording_url="https://rec",
            from_number="+5511999999999",
            recording_duration=4.0,
        )

    reset.assert_called_once()
    mark_ready.assert_called_once()
    assert mark_ready.call_args.kwargs["audio_filename"].endswith(".mp3")


@pytest.mark.asyncio
async def test_process_turn_empty_transcript_marks_silence(monkeypatch) -> None:
    with (
        patch(
            "app.services.voice_turn_processor.download_recording",
            new=AsyncMock(return_value=b"RIFFwav"),
        ),
        patch(
            "app.services.voice_turn_processor.speech_to_text",
            new=AsyncMock(return_value=""),
        ),
        patch("app.services.voice_turn_processor.mark_turn_silence_stt") as mark_silence,
    ):
        await process_voice_inbound_turn(
            call_sid="CAsilence",
            turn_id="tw2",
            recording_url="https://rec",
            from_number="+5511999999999",
            recording_duration=3.0,
        )

    mark_silence.assert_called_once_with("CAsilence", "tw2")
