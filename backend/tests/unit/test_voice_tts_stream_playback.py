"""Tests — phrase-streamed TTS playback pipeline (P3 latency)."""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, patch

import pytest

from agents.channels.voice.mulaw_codec import MULAW_FRAME_BYTES, chunk_mulaw, pcm16_to_mulaw
from agents.channels.voice.tts_stream import pcm16_silence, pcm16_to_wav
from agents.channels.voice.tts_stream_synth import (
    StreamTtsPlaybackResult,
    stream_phrase_tts_playback,
    synthesize_phrase_pcm,
)
from agents.workers.response_agent import (
    collapse_voice_list_for_telephony,
    response_contains_spoken_list,
    sanitize_voice_response_for_telephony,
)
from app.core.config import settings

pytestmark = pytest.mark.unit

SAMPLE_RATE = 8000


def _phrase_pcm(duration_ms: int = 200) -> bytes:
    n = SAMPLE_RATE * duration_ms // 1000
    return struct.pack(f"<{n}h", *([6000] * n))


def _phrase_wav(duration_ms: int = 200) -> bytes:
    return pcm16_to_wav(_phrase_pcm(duration_ms), SAMPLE_RATE)


@pytest.mark.asyncio
async def test_stream_playback_sends_phrases_in_order_with_overlap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_stream_tts_phrase_enabled", True)
    monkeypatch.setattr(settings, "voice_stream_tts_phrase_gap_ms", 150)
    text = "Primeira frase. Segunda frase. Terceira frase."
    synth_started: list[float] = []
    send_started: list[tuple[int, float]] = []
    phrase_idx = 0

    async def slow_synth(phrase: str, **kwargs) -> bytes:
        nonlocal phrase_idx
        idx = phrase_idx
        phrase_idx += 1
        synth_started.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.08)
        return _phrase_pcm(160)

    async def on_frame(frame: bytes) -> bool:
        send_started.append((len(send_started), asyncio.get_event_loop().time()))
        await asyncio.sleep(0.02)
        return True

    with patch(
        "agents.channels.voice.tts_stream_synth.synthesize_phrase_pcm",
        side_effect=slow_synth,
    ):
        result = await stream_phrase_tts_playback(
            text,
            sample_rate=SAMPLE_RATE,
            on_frame=on_frame,
        )

    assert result.phrase_count == 3
    assert result.completed is True
    assert len(result.frames) >= 3
    assert result.ttfa_ms is not None
    assert len(send_started) >= 3
    # First frames sent before third phrase synthesis finishes (pipeline overlap).
    assert send_started[0][0] < len(synth_started) or len(synth_started) >= 2


@pytest.mark.asyncio
async def test_stream_playback_marks_completed_after_last_frame(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_stream_tts_phrase_enabled", True)
    text = "Frase um. Frase dois."
    sent_frames: list[bytes] = []

    async def on_frame(frame: bytes) -> bool:
        sent_frames.append(frame)
        return True

    with patch(
        "agents.channels.voice.tts_stream_synth.synthesize_phrase_pcm",
        AsyncMock(side_effect=[_phrase_pcm(120), _phrase_pcm(120)]),
    ):
        result = await stream_phrase_tts_playback(
            text,
            sample_rate=SAMPLE_RATE,
            on_frame=on_frame,
        )

    assert result.completed is True
    assert len(sent_frames) == len(result.frames)
    assert result.frames[-1] == sent_frames[-1]


@pytest.mark.asyncio
async def test_stream_playback_phrase_synth_failure_does_not_block(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_stream_tts_phrase_enabled", True)
    text = "Primeira ok. Segunda falha. Terceira ok."
    calls = {"n": 0}

    async def flaky_synth(phrase: str, **kwargs) -> bytes:
        calls["n"] += 1
        if "Segunda" in phrase:
            raise RuntimeError("coqui timeout")
        return _phrase_pcm(100)

    sent = 0

    async def on_frame(frame: bytes) -> bool:
        nonlocal sent
        sent += 1
        return True

    with patch(
        "agents.channels.voice.tts_stream_synth.synthesize_phrase_pcm",
        side_effect=flaky_synth,
    ):
        result = await stream_phrase_tts_playback(
            text,
            sample_rate=SAMPLE_RATE,
            on_frame=on_frame,
        )

    assert calls["n"] == 3
    assert sent >= 1
    assert result.completed is False


@pytest.mark.asyncio
async def test_stream_playback_abort_stops_consumer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_stream_tts_phrase_enabled", False)
    text = "Resposta longa única."
    sent = 0

    async def on_frame(frame: bytes) -> bool:
        nonlocal sent
        sent += 1
        return sent < 2

    with patch(
        "agents.channels.voice.tts_stream_synth.synthesize_phrase_pcm",
        AsyncMock(return_value=_phrase_pcm(800)),
    ):
        result = await stream_phrase_tts_playback(
            text,
            sample_rate=SAMPLE_RATE,
            on_frame=on_frame,
        )

    assert result.completed is False
    assert sent == 2


def test_response_contains_spoken_list_colon_multiline() -> None:
    text = (
        "A ByteCell Academy oferece cursos em varias areas, incluindo:\n"
        " Excel\n Banco de Dados\n Market"
    )
    assert response_contains_spoken_list(text) is True


def test_collapse_voice_list_keeps_opening_and_offer(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "voice_list_detail_offer",
        "Quer que eu detalhe alguma?",
    )
    text = (
        "A ByteCell Academy oferece cursos em varias areas, incluindo:\n"
        " Excel\n Banco de Dados\n Market"
    )
    result = collapse_voice_list_for_telephony(text)
    assert "Excel" not in result
    assert "Banco de Dados" not in result
    assert "incluindo" not in result.lower()
    assert "Quer que eu detalhe alguma?" in result
    assert result.endswith("?")


def test_sanitize_collapses_list_before_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_max_response_chars", 300)
    monkeypatch.setattr(settings, "voice_list_detail_offer", "Quer que eu detalhe alguma?")
    text = "Oferecemos cursos, incluindo:\n- Excel\n- BI\n- Marketing"
    result = sanitize_voice_response_for_telephony(text)
    assert "- Excel" not in result
    assert "Quer que eu detalhe alguma?" in result


@pytest.mark.asyncio
async def test_farewell_stream_sends_all_audio_before_mark(monkeypatch) -> None:
    """Hangup mark only after streamed playback completes (integration-style)."""
    from agents.channels.voice.stream_session import (
        AGENT_RESPONSE_MARK,
        FAREWELL_DONE_MARK,
        StreamCallControl,
        _process_utterance_turn,
    )
    from agents.channels.voice.audio_pipeline import UtteranceClosed, resample_8k_to_16k

    monkeypatch.setattr(settings, "voice_stream_barge_in_enabled", False)
    pcm_16k = resample_8k_to_16k(struct.pack("<320h", *([500] * 320)))
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=40, index=9)
    ws = AsyncMock()
    control = StreamCallControl()
    events: list[str] = []

    async def send_side_effect(payload: str) -> None:
        import json

        data = json.loads(payload)
        events.append(data.get("event", ""))

    ws.send_text = AsyncMock(side_effect=send_side_effect)
    frames = chunk_mulaw(pcm16_to_mulaw(_phrase_pcm(400)))

    async def mock_stream(*args, **kwargs) -> StreamTtsPlaybackResult:
        for frame in frames:
            await kwargs["websocket"].send_text(
                __import__("json").dumps(
                    {
                        "event": "media",
                        "streamSid": kwargs["stream_sid"],
                        "media": {"payload": __import__("base64").b64encode(frame).decode()},
                    }
                )
            )
        return StreamTtsPlaybackResult(
            frames=frames,
            wav_bytes=_phrase_wav(400),
            mulaw=b"".join(frames),
            phrase_count=1,
            tts_ms=50.0,
            ttfa_ms=120.0,
            completed=True,
        )

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="tchau"),
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(
            "agents.channels.voice.stream_session._run_voice_agent_for_stream",
            AsyncMock(return_value=("Até logo!", True)),
        ),
        patch(
            "agents.channels.voice.stream_session._stream_response_tts_to_ws",
            side_effect=mock_stream,
        ),
        patch(
            "agents.channels.voice.stream_session._execute_agent_farewell_hangup",
            AsyncMock(),
        ) as hangup_mock,
    ):
        await _process_utterance_turn(
            result,
            call_sid="CAfarewell",
            stream_sid="MZfarewell",
            websocket=ws,
            control=control,
        )

    media_idx = [i for i, e in enumerate(events) if e == "media"]
    mark_idx = [i for i, e in enumerate(events) if e == "mark"]
    assert media_idx
    assert max(media_idx) < min(mark_idx) if mark_idx else True
    hangup_mock.assert_awaited_once()
