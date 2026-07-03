"""
Inbound audio pipeline for Twilio Media Streams (Fase B).

μ-law 8 kHz → PCM → linear resample 16 kHz → webrtcvad → utterance boundaries.
Resample is pure Python (no numpy/scipy/ffmpeg): adequate for VAD; Whisper quality
to be validated in Fase C.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agents.channels.voice.mulaw_codec import mulaw_to_pcm16

logger = logging.getLogger(__name__)

SAMPLE_RATE_8K = 8000
SAMPLE_RATE_16K = 16000

_voice_stream_available: bool | None = None

# Extension hook for Fase C (STT per utterance).
OnUtteranceClosed = Callable[["UtteranceClosed"], None]


class _VadLike(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


@dataclass(frozen=True)
class UtteranceClosed:
    """One closed speech segment ready for STT (Fase C)."""

    pcm16_16k: bytes
    duration_ms: int
    index: int


@dataclass
class VoiceStreamSession:
    """
    Per-call inbound audio state: decode, resample, VAD, utterance buffer.

    ``listening`` gates processing until the intro beep finishes (anti-echo).
    """

    vad: _VadLike = field(repr=False)
    call_sid: str | None = None
    stream_sid: str | None = None
    frame_ms: int = 20
    silence_hangover_ms: int = 600
    min_utterance_ms: int = 400
    max_utterance_ms: int = 30000
    pcm_buffer: bytearray = field(default_factory=bytearray)
    in_speech: bool = False
    silence_frames: int = 0
    speech_frames: int = 0
    utterance_count: int = 0
    listening: bool = False

    @property
    def _hangover_frames(self) -> int:
        return max(1, self.silence_hangover_ms // self.frame_ms)

    @property
    def _min_speech_frames(self) -> int:
        return max(1, self.min_utterance_ms // self.frame_ms)

    @property
    def _max_speech_frames(self) -> int:
        return max(1, self.max_utterance_ms // self.frame_ms)

    @property
    def _pcm_frame_bytes_16k(self) -> int:
        samples = SAMPLE_RATE_16K * self.frame_ms // 1000
        return samples * 2

    def _duration_ms(self) -> int:
        return len(self.pcm_buffer) * 1000 // (SAMPLE_RATE_16K * 2)

    def _reset_utterance_state(self) -> None:
        self.pcm_buffer.clear()
        self.in_speech = False
        self.silence_frames = 0
        self.speech_frames = 0

    def _close_utterance(self, *, forced: bool = False) -> UtteranceClosed | None:
        duration_ms = self._duration_ms()
        if not forced and self.speech_frames < self._min_speech_frames:
            logger.debug(
                "Voice stream utterance discarded (too short %sms) callSid=%s",
                duration_ms,
                self.call_sid or "?",
            )
            self._reset_utterance_state()
            return None

        if not self.pcm_buffer:
            self._reset_utterance_state()
            return None

        self.utterance_count += 1
        result = UtteranceClosed(
            pcm16_16k=bytes(self.pcm_buffer),
            duration_ms=duration_ms,
            index=self.utterance_count,
        )
        self._reset_utterance_state()
        return result

    def feed_mulaw_frame(self, frame_mulaw_8k: bytes) -> UtteranceClosed | None:
        """Process one Twilio μ-law frame (~20 ms @ 8 kHz). Runs inline (CPU-light)."""
        if not self.listening or not frame_mulaw_8k:
            return None

        pcm_8k = mulaw_to_pcm16(frame_mulaw_8k)
        pcm_16k = resample_8k_to_16k(pcm_8k)
        frame_bytes = self._pcm_frame_bytes_16k
        if len(pcm_16k) != frame_bytes:
            logger.warning(
                "Voice stream resample size mismatch got=%s expected=%s callSid=%s",
                len(pcm_16k),
                frame_bytes,
                self.call_sid or "?",
            )
            return None

        is_speech = self.vad.is_speech(pcm_16k, SAMPLE_RATE_16K)

        if is_speech:
            self.in_speech = True
            self.pcm_buffer.extend(pcm_16k)
            self.silence_frames = 0
            self.speech_frames += 1
            if self.speech_frames >= self._max_speech_frames:
                return self._close_utterance(forced=True)
            return None

        if self.in_speech:
            self.silence_frames += 1
            self.pcm_buffer.extend(pcm_16k)
            if self.silence_frames >= self._hangover_frames:
                return self._close_utterance(forced=False)

        return None

    def flush(self) -> UtteranceClosed | None:
        """Close a pending utterance on stop/disconnect (speech without trailing silence)."""
        if not self.in_speech or not self.pcm_buffer:
            self._reset_utterance_state()
            return None
        return self._close_utterance(forced=True)


def resample_8k_to_16k(pcm16_8k: bytes) -> bytes:
    """
    Upsample mono PCM int16 LE from 8 kHz to 16 kHz via linear interpolation.

    160 samples (20 ms) → 320 samples (20 ms). Pure Python — no extra deps.
    """
    n_in = len(pcm16_8k) // 2
    if n_in == 0:
        return b""

    samples_in = struct.unpack(f"<{n_in}h", pcm16_8k)
    n_out = n_in * 2
    out = bytearray(n_out * 2)

    for i in range(n_out):
        src = i / 2.0
        idx = int(src)
        frac = src - idx
        if idx >= n_in - 1:
            value = samples_in[n_in - 1]
        else:
            s0 = samples_in[idx]
            s1 = samples_in[idx + 1]
            value = int(s0 + (s1 - s0) * frac)
        value = max(-32768, min(32767, value))
        struct.pack_into("<h", out, i * 2, value)

    return bytes(out)


def _create_webrtc_vad(aggressiveness: int) -> _VadLike:
    import webrtcvad

    return webrtcvad.Vad(aggressiveness)


def is_voice_stream_available() -> bool:
    """
    Return whether webrtcvad is importable (stream mode can run).

    Result is cached after the first check; import stays lazy (never at app boot).
    """
    global _voice_stream_available
    if _voice_stream_available is not None:
        return _voice_stream_available
    try:
        import webrtcvad  # noqa: F401

        _voice_stream_available = True
    except ImportError:
        _voice_stream_available = False
    return _voice_stream_available


def create_voice_stream_session(
    *,
    call_sid: str | None,
    stream_sid: str | None,
    aggressiveness: int = 2,
    frame_ms: int = 20,
    silence_hangover_ms: int = 600,
    min_utterance_ms: int = 400,
    max_utterance_ms: int = 30000,
    vad: _VadLike | None = None,
) -> VoiceStreamSession:
    """Build session with webrtcvad configured from settings/env."""
    if frame_ms not in (10, 20, 30):
        raise ValueError(f"frame_ms must be 10, 20 or 30, got {frame_ms}")

    vad_impl = vad if vad is not None else _create_webrtc_vad(int(aggressiveness))
    return VoiceStreamSession(
        vad=vad_impl,
        call_sid=call_sid,
        stream_sid=stream_sid,
        frame_ms=frame_ms,
        silence_hangover_ms=silence_hangover_ms,
        min_utterance_ms=min_utterance_ms,
        max_utterance_ms=max_utterance_ms,
        listening=False,
    )


def create_voice_stream_session_from_settings(
    *,
    call_sid: str | None,
    stream_sid: str | None,
    settings: Any,
) -> VoiceStreamSession:
    """Factory using ``app.core.config.settings`` fields."""
    return create_voice_stream_session(
        call_sid=call_sid,
        stream_sid=stream_sid,
        aggressiveness=int(settings.voice_stream_vad_aggressiveness),
        frame_ms=int(settings.voice_stream_vad_frame_ms),
        silence_hangover_ms=int(settings.voice_stream_silence_hangover_ms),
        min_utterance_ms=int(settings.voice_stream_min_utterance_ms),
        max_utterance_ms=int(settings.voice_stream_max_utterance_ms),
    )
