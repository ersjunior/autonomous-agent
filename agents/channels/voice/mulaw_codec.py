"""G.711 μ-law codec utilities for Twilio Media Streams (8 kHz, raw bytes)."""

from __future__ import annotations

import math
import struct

# Twilio Media Streams: ~20 ms @ 8 kHz mono μ-law
MULAW_FRAME_BYTES = 160
SAMPLE_RATE = 8000

_MULAW_BIAS = 0x84
_MULAW_CLIP = 32635
_MULAW_EXP_TABLE: tuple[int, ...] = tuple(
    [0, 0, 1, 1, 2, 2, 2, 2]
    + [3] * 8
    + [4] * 16
    + [5] * 32
    + [6] * 64
    + [7] * 128
)


def _linear_to_mulaw(sample: int) -> int:
    """Encode one PCM 16-bit signed sample to a G.711 μ-law byte."""
    sign = (sample >> 8) & 0x80
    if sign:
        sample = -sample
    if sample > _MULAW_CLIP:
        sample = _MULAW_CLIP
    sample += _MULAW_BIAS
    exponent = _MULAW_EXP_TABLE[(sample >> 7) & 0xFF]
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def pcm16_to_mulaw(pcm: bytes) -> bytes:
    """Convert little-endian PCM 16-bit mono buffer to raw μ-law bytes."""
    out = bytearray(len(pcm) // 2)
    for i in range(0, len(pcm), 2):
        sample = struct.unpack("<h", pcm[i : i + 2])[0]
        out[i // 2] = _linear_to_mulaw(sample)
    return bytes(out)


def chunk_mulaw(data: bytes, frame_size: int = MULAW_FRAME_BYTES) -> list[bytes]:
    """Split raw μ-law bytes into Twilio-sized frames (~20 ms each)."""
    if not data:
        return []
    return [
        data[offset : offset + frame_size]
        for offset in range(0, len(data), frame_size)
        if data[offset : offset + frame_size]
    ]


def generate_intro_beep_mulaw(
    *,
    frequency_hz: float = 440.0,
    duration_sec: float = 0.45,
    sample_rate: int = SAMPLE_RATE,
) -> bytes:
    """
    Generate a short sine tone as raw μ-law @ 8 kHz (no WAV header).

    Used on stream connect to verify outbound audio path to the caller.
    """
    n_samples = int(sample_rate * duration_sec)
    pcm = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        edge = min(1.0, i / 80.0, (n_samples - i) / 80.0)
        sample = int(12000 * edge * math.sin(2.0 * math.pi * frequency_hz * t))
        sample = max(-32768, min(32767, sample))
        pcm.extend(struct.pack("<h", sample))
    return pcm16_to_mulaw(bytes(pcm))


INTRO_MULAW: bytes = generate_intro_beep_mulaw()
INTRO_FRAMES: list[bytes] = chunk_mulaw(INTRO_MULAW)
