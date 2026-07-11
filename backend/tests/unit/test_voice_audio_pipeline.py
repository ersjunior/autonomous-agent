"""Unit tests — voice stream audio pipeline (decode, resample, VAD state machine)."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest

from agents.channels.voice.audio_pipeline import (
    create_voice_stream_session,
    create_voice_stream_session_from_settings,
    pcm16_16k_to_wav,
    resample_8k_to_16k,
)
from agents.channels.voice.mulaw_codec import (
    INTRO_FRAMES,
    MULAW_FRAME_BYTES,
    chunk_mulaw,
    generate_intro_beep_mulaw,
    mulaw_to_pcm16,
    pcm16_to_mulaw,
)

pytestmark = pytest.mark.unit

MULAW_SILENCE_FRAME = bytes([0xFF] * MULAW_FRAME_BYTES)


def _pcm16_frame_8k(value: int = 0, n_samples: int = 160) -> bytes:
    return struct.pack(f"<{n_samples}h", *([value] * n_samples))


class MockVad:
    """Deterministic speech/silence sequence for state-machine tests."""

    def __init__(self, pattern: list[bool]) -> None:
        self._pattern = list(pattern)
        self._index = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if self._index >= len(self._pattern):
            return False
        result = self._pattern[self._index]
        self._index += 1
        return result


def test_mulaw_to_pcm16_round_trip_tolerance() -> None:
    original = _pcm16_frame_8k(5000, 160) + _pcm16_frame_8k(-8000, 160)
    mulaw = pcm16_to_mulaw(original)
    recovered = mulaw_to_pcm16(mulaw)

    assert len(recovered) == len(original)
    orig_samples = struct.unpack(f"<{len(original) // 2}h", original)
    recv_samples = struct.unpack(f"<{len(recovered) // 2}h", recovered)
    for o, r in zip(orig_samples, recv_samples, strict=True):
        assert abs(o - r) <= 2048


def test_resample_8k_to_16k_doubles_samples() -> None:
    pcm_8k = _pcm16_frame_8k(1000, 160)
    pcm_16k = resample_8k_to_16k(pcm_8k)
    assert len(pcm_16k) == len(pcm_8k) * 2
    assert len(pcm_16k) // 2 == 320


def test_pcm16_16k_to_wav_valid_container() -> None:
    import io
    import wave

    pcm_16k = resample_8k_to_16k(_pcm16_frame_8k(1000, 160))
    wav = pcm16_16k_to_wav(pcm_16k)

    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"

    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getsampwidth() == 2
        assert wf.readframes(wf.getnframes()) == pcm_16k


def test_create_voice_stream_session_from_settings_with_real_settings() -> None:
    from app.core.config import settings

    mock_vad = MagicMock()
    with patch(
        "agents.channels.voice.audio_pipeline._create_webrtc_vad",
        return_value=mock_vad,
    ):
        session = create_voice_stream_session_from_settings(
            call_sid="CAfactory",
            stream_sid="MZfactory",
            settings=settings,
        )

    assert session.call_sid == "CAfactory"
    assert session.stream_sid == "MZfactory"
    assert session.frame_ms == int(settings.voice_stream_vad_frame_ms)
    assert session.silence_hangover_ms == int(settings.voice_stream_silence_hangover_ms)


def test_vad_state_machine_one_utterance() -> None:
    hangover_frames = 600 // 20
    silence_lead = 5
    speech_frames = 25
    silence_tail = hangover_frames

    pattern: list[bool] = (
        [False] * silence_lead
        + [True] * speech_frames
        + [False] * silence_tail
    )
    vad = MockVad(pattern)
    session = create_voice_stream_session(
        call_sid="CAtest",
        stream_sid="MZtest",
        silence_hangover_ms=600,
        min_utterance_ms=400,
        frame_ms=20,
        vad=vad,
    )
    session.listening = True

    closed = None
    for _ in range(silence_lead + speech_frames + silence_tail + 2):
        result = session.feed_mulaw_frame(MULAW_SILENCE_FRAME)
        if result.utterance is not None:
            closed = result.utterance
            break

    assert closed is not None
    assert closed.index == 1
    assert closed.duration_ms >= 400
    assert len(closed.pcm16_16k) > 0


def test_min_utterance_discards_short_speech() -> None:
    vad = MockVad([True] * 5 + [False] * 40)
    session = create_voice_stream_session(
        call_sid="CAshort",
        stream_sid="MZshort",
        min_utterance_ms=400,
        silence_hangover_ms=600,
        frame_ms=20,
        vad=vad,
    )
    session.listening = True

    for _ in range(45):
        session.feed_mulaw_frame(MULAW_SILENCE_FRAME)

    assert session.utterance_count == 0


def test_flush_closes_pending_utterance() -> None:
    vad = MockVad([True] * 30)
    session = create_voice_stream_session(
        call_sid="CAflush",
        stream_sid="MZflush",
        min_utterance_ms=400,
        frame_ms=20,
        vad=vad,
    )
    session.listening = True

    tone = chunk_mulaw(generate_intro_beep_mulaw(duration_sec=0.04))[0]
    for _ in range(30):
        session.feed_mulaw_frame(tone)

    flushed = session.flush()
    assert flushed is not None
    assert flushed.index == 1
    assert flushed.duration_ms >= 400


def test_agent_playback_gate_ignores_echo_when_barge_off() -> None:
    from agents.channels.voice.stream_session import StreamCallControl

    control = StreamCallControl()
    control.begin_agent_playback()
    vad = MockVad([True] * 40)
    session = create_voice_stream_session(
        call_sid="CAecho",
        stream_sid="MZecho",
        barge_in_enabled=False,
        vad=vad,
    )
    session.listening = True
    session.agent_speaking_check = lambda: control.agent_speaking

    for _ in range(40):
        result = session.feed_mulaw_frame(MULAW_SILENCE_FRAME)
        assert result.utterance is None

    assert session.utterance_count == 0
    assert vad._index == 0


def test_agent_playback_gate_reopens_after_mark_semantics() -> None:
    from agents.channels.voice.stream_session import StreamCallControl

    control = StreamCallControl()
    control.begin_agent_playback()
    hangover = 600 // 20
    vad = MockVad([True] * 25 + [False] * hangover)
    session = create_voice_stream_session(
        call_sid="CAreopen",
        stream_sid="MZreopen",
        barge_in_enabled=False,
        silence_hangover_ms=600,
        min_utterance_ms=400,
        frame_ms=20,
        vad=vad,
    )
    session.listening = True
    session.agent_speaking_check = lambda: control.agent_speaking

    control.end_agent_playback()

    closed = None
    for _ in range(60):
        result = session.feed_mulaw_frame(MULAW_SILENCE_FRAME)
        if result.utterance is not None:
            closed = result.utterance
            break

    assert closed is not None
    assert closed.index == 1


def test_is_voice_stream_available_caches_result(monkeypatch) -> None:
    from agents.channels.voice import audio_pipeline as ap

    ap._voice_stream_available = None
    calls = {"n": 0}

    def _fake_import(name, *args, **kwargs):
        calls["n"] += 1
        if name == "webrtcvad":
            return MagicMock()
        return __import__(name, *args, **kwargs)

    monkeypatch.setattr(ap, "_voice_stream_available", None)
    with patch("builtins.__import__", side_effect=_fake_import):
        assert ap.is_voice_stream_available() is True
        assert ap.is_voice_stream_available() is True
    assert calls["n"] == 1
    ap._voice_stream_available = None


def test_is_voice_stream_available_false_on_import_error(monkeypatch) -> None:
    from agents.channels.voice import audio_pipeline as ap

    ap._voice_stream_available = None

    def _fail_import(name, *args, **kwargs):
        if name == "webrtcvad":
            raise ModuleNotFoundError("webrtcvad")
        return __import__(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_fail_import):
        assert ap.is_voice_stream_available() is False
    ap._voice_stream_available = None


def test_listening_gate_ignores_frames_before_enable() -> None:
    vad = MagicMock()
    vad.is_speech.return_value = True
    session = create_voice_stream_session(
        call_sid="CAgate",
        stream_sid="MZgate",
        vad=vad,
    )
    assert session.listening is False

    tone = chunk_mulaw(generate_intro_beep_mulaw(duration_sec=0.02))[0]
    session.feed_mulaw_frame(tone)
    vad.is_speech.assert_not_called()

    session.listening = True
    session.feed_mulaw_frame(tone)
    vad.is_speech.assert_called_once()


def test_intro_frames_are_exactly_160_bytes() -> None:
    assert len(INTRO_FRAMES) > 0
    assert all(len(frame) == MULAW_FRAME_BYTES for frame in INTRO_FRAMES)


def test_chunk_mulaw_exact_multiple_all_160() -> None:
    data = bytes(range(256)) * 2
    frames = chunk_mulaw(data, frame_size=160)
    assert len(frames) == 4
    assert all(len(f) == MULAW_FRAME_BYTES for f in frames)


def test_chunk_mulaw_pads_partial_last_frame_with_silence() -> None:
    data = b"\x55" * 400
    frames = chunk_mulaw(data)
    assert len(frames) == 3
    assert all(len(f) == MULAW_FRAME_BYTES for f in frames)
    assert frames[2][:80] == b"\x55" * 80
    assert frames[2][80:] == bytes([0xFF]) * 80


def test_pcm16_to_mulaw_ignores_trailing_odd_byte() -> None:
    pcm = b"\x00\x01" * 10 + b"\x99"
    mulaw = pcm16_to_mulaw(pcm)
    assert len(mulaw) == 10
