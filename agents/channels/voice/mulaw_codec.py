"""G.711 μ-law codec utilities for Twilio Media Streams (8 kHz, raw bytes)."""

from __future__ import annotations

import io
import math
import struct
import wave

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


def _mulaw_to_linear(mulaw_byte: int) -> int:
    """Decode one G.711 μ-law byte to PCM 16-bit signed (ITU-T inverse of encode)."""
    mu = (~mulaw_byte) & 0xFF
    sign = mu & 0x80
    exponent = (mu >> 4) & 0x07
    mantissa = mu & 0x0F
    sample = ((mantissa << 3) + _MULAW_BIAS) << exponent
    sample -= _MULAW_BIAS
    if sign:
        sample = -sample
    return max(-32768, min(32767, sample))


def mulaw_to_pcm16(data: bytes) -> bytes:
    """Convert raw μ-law bytes to little-endian PCM 16-bit mono."""
    out = bytearray(len(data) * 2)
    for i, byte in enumerate(data):
        struct.pack_into("<h", out, i * 2, _mulaw_to_linear(byte))
    return bytes(out)


def wav_bytes_to_pcm16_mono(wav_bytes: bytes, *, expected_rate: int = 8000) -> bytes:
    """Extract mono PCM16 LE payload from a WAV container."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError(f"expected mono WAV, got {wf.getnchannels()} channels")
        if wf.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got sampwidth={wf.getsampwidth()}")
        rate = wf.getframerate()
        if rate != expected_rate:
            raise ValueError(f"expected {expected_rate} Hz WAV, got {rate} Hz")
        return wf.readframes(wf.getnframes())


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
