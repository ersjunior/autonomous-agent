"""Tests — voice stream debug audio capture (P2 bisection, best-effort)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.channels.voice.audio_debug_capture import (
    debug_save_dir,
    frames_to_mulaw,
    pcm16_8k_to_wav,
    save_voice_stream_debug_capture,
    schedule_voice_stream_debug_capture,
)
from agents.channels.voice.mulaw_codec import (
    MULAW_FRAME_BYTES,
    MULAW_SILENCE_BYTE,
    chunk_mulaw,
    mulaw_to_pcm16,
    pcm16_to_mulaw,
)
from agents.channels.voice.stream_session import StreamTtsResult, _process_utterance_turn
from agents.channels.voice.tts_stream_synth import StreamTtsPlaybackResult
from agents.channels.voice.audio_pipeline import UtteranceClosed
from app.core.config import settings

pytestmark = pytest.mark.unit


def _make_wav_8k(num_samples: int = 800) -> bytes:
    pcm = b"\x00\x10" * num_samples
    return pcm16_8k_to_wav(pcm)


@pytest.fixture
def debug_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "voice_debug"
    monkeypatch.setattr(settings, "voice_stream_debug_save_dir", str(target))
    monkeypatch.setattr(settings, "voice_audio_root", str(tmp_path / "voice_audio"))
    return target


def test_debug_save_dir_default_uses_voice_audio_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_stream_debug_save_dir", "")
    monkeypatch.setattr(settings, "voice_audio_root", "/workspace/voice_audio")
    assert debug_save_dir() == Path("/workspace/voice_audio/debug")


def test_debug_save_dir_custom_override(debug_dir: Path) -> None:
    assert debug_save_dir() == debug_dir


@pytest.mark.asyncio
async def test_save_capture_flag_off_writes_nothing(
    debug_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_stream_debug_save_audio", False)
    frames = chunk_mulaw(bytes([MULAW_SILENCE_BYTE]) * 320)
    await save_voice_stream_debug_capture(
        call_sid="CAoff",
        utterance_index=1,
        transcript="oi",
        response_text="Olá!",
        coqui_wav_bytes=_make_wav_8k(),
        mulaw_frames=frames,
    )
    assert not debug_dir.exists() or list(debug_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_save_capture_flag_on_writes_all_files(
    debug_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_stream_debug_save_audio", True)
    coqui = _make_wav_8k(160)
    pcm = b"\x00\x20" * 160
    mulaw = pcm16_to_mulaw(pcm)
    frames = chunk_mulaw(mulaw)

    await save_voice_stream_debug_capture(
        call_sid="CAon123",
        utterance_index=2,
        transcript="quero ajuda",
        response_text="Claro, como posso ajudar?",
        coqui_wav_bytes=coqui,
        mulaw_frames=frames,
        extra={"agent_ms": 120.5},
    )

    stem = "CAon123_u2"
    assert (debug_dir / f"{stem}_coqui_8k.wav").read_bytes() == coqui
    mulaw_out = frames_to_mulaw(frames)
    assert (debug_dir / f"{stem}_out.mulaw").read_bytes() == mulaw_out
    out_wav = (debug_dir / f"{stem}_out.wav").read_bytes()
    assert out_wav[:4] == b"RIFF"
    assert mulaw_to_pcm16(mulaw_out) in out_wav

    meta = json.loads((debug_dir / f"{stem}_meta.json").read_text(encoding="utf-8"))
    assert meta["call_sid"] == "CAon123"
    assert meta["utterance_index"] == 2
    assert meta["transcript"] == "quero ajuda"
    assert meta["response_text"] == "Claro, como posso ajudar?"
    assert meta["coqui_wav_bytes"] == len(coqui)
    assert meta["mulaw_out_bytes"] == len(mulaw_out)
    assert meta["mulaw_frames_count"] == len(frames)
    assert meta["mulaw_frame_bytes"] == MULAW_FRAME_BYTES
    assert meta["agent_ms"] == 120.5


@pytest.mark.asyncio
async def test_save_capture_write_failure_does_not_raise(
    debug_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_stream_debug_save_audio", True)

    with patch(
        "agents.channels.voice.audio_debug_capture._write_capture_files_sync",
        side_effect=OSError("disk full"),
    ):
        await save_voice_stream_debug_capture(
            call_sid="CAfail",
            utterance_index=1,
            transcript="x",
            response_text="y",
            coqui_wav_bytes=b"wav",
            mulaw_frames=[bytes([MULAW_SILENCE_BYTE]) * MULAW_FRAME_BYTES],
        )


def test_schedule_capture_flag_off_no_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "voice_stream_debug_save_audio", False)
    created: list[asyncio.Task[object]] = []
    real_create_task = asyncio.create_task

    def _track(coro, *, name=None):
        task = real_create_task(coro, name=name)
        created.append(task)
        return task

    with patch("asyncio.create_task", side_effect=_track):
        schedule_voice_stream_debug_capture(
            call_sid="CAx",
            utterance_index=1,
            transcript="a",
            response_text="b",
            coqui_wav_bytes=b"w",
            mulaw_frames=[],
        )

    assert created == []


@pytest.mark.asyncio
async def test_schedule_capture_flag_on_creates_background_task(
    debug_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_stream_debug_save_audio", True)
    frames = chunk_mulaw(bytes([MULAW_SILENCE_BYTE]) * 320)

    schedule_voice_stream_debug_capture(
        call_sid="CAbg",
        utterance_index=3,
        transcript="ola",
        response_text="Oi!",
        coqui_wav_bytes=_make_wav_8k(),
        mulaw_frames=frames,
    )

    await asyncio.sleep(0.05)
    assert (debug_dir / "CAbg_u3_coqui_8k.wav").is_file()
    assert (debug_dir / "CAbg_u3_out.mulaw").is_file()
    assert (debug_dir / "CAbg_u3_out.wav").is_file()
    assert (debug_dir / "CAbg_u3_meta.json").is_file()


@pytest.mark.asyncio
async def test_process_utterance_turn_continues_when_capture_write_fails(
    debug_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from agents.channels.voice.stream_session import StreamCallControl

    monkeypatch.setattr(settings, "voice_stream_debug_save_audio", True)
    pcm_16k = b"\x00\x00" * 320
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=40, index=1)
    ws = AsyncMock()
    frames = [bytes([MULAW_SILENCE_BYTE]) * MULAW_FRAME_BYTES]

    async def stream_send(*args, **kwargs) -> StreamTtsPlaybackResult:
        for frame in frames:
            await kwargs["websocket"].send_text(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": kwargs["stream_sid"],
                        "media": {
                            "payload": __import__("base64").b64encode(frame).decode("ascii"),
                        },
                    }
                )
            )
        return StreamTtsPlaybackResult(
            frames=frames,
            wav_bytes=b"RIFFcoqui",
            mulaw=b"\xff" * 160,
            completed=True,
            phrase_count=1,
        )

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="oi"),
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(
            "agents.channels.voice.stream_session._run_voice_agent_for_stream",
            AsyncMock(return_value=("Resposta ok.", False)),
        ),
        patch(
            "agents.channels.voice.stream_session._stream_response_tts_to_ws",
            side_effect=stream_send,
        ),
        patch(
            "agents.channels.voice.audio_debug_capture._write_capture_files_sync",
            side_effect=OSError("disk full"),
        ),
    ):
        await _process_utterance_turn(
            result,
            call_sid="CAcont",
            stream_sid="MZcont",
            websocket=ws,
            control=StreamCallControl(),
        )

    sent = [c.args[0] for c in ws.send_text.await_args_list]
    assert any('"event": "media"' in s for s in sent)
