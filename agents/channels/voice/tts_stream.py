"""Voice stream TTS: phrase splitting, PCM concat, and run-on trim (P2/P3)."""

from __future__ import annotations

import io
import logging
import math
import re
import struct
import wave
from dataclasses import dataclass

logger = logging.getLogger("app.voice_stream_tts")

DEFAULT_MS_PER_CHAR = 75.0
DEFAULT_MAX_DURATION_FACTOR = 1.5
DEFAULT_PHRASE_GAP_MS = 150
DEFAULT_CLAUSE_GAP_MS = 70
DEFAULT_PHRASE_MAX_CHARS = 45
SILENCE_RMS_THRESHOLD = 80
TRIM_SILENCE_RMS_THRESHOLD = 80
FRAME_MS = 20
MIN_SILENCE_MS = 200
DEFAULT_FADE_OUT_MS = 15

_CONJUNCTION_SPLIT_RE = re.compile(
    r"\s+(?:e|ou|mas|porém|porem|que|para|com|sobre|incluindo)\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TtsPhraseSegment:
    """One TTS chunk plus pause before the next (0 = last chunk)."""

    text: str
    gap_after_ms: int = 0


def _split_at_word_boundary(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    rest = (text or "").strip()
    while len(rest) > max_chars:
        window = rest[:max_chars]
        last_space = window.rfind(" ")
        if last_space <= 0:
            parts.append(rest[:max_chars].strip())
            rest = rest[max_chars:].strip()
            continue
        parts.append(rest[:last_space].strip())
        rest = rest[last_space:].strip()
    if rest:
        parts.append(rest)
    return parts


def _subdivide_sentence(sentence: str, *, max_chars: int) -> list[str]:
    sentence = (sentence or "").strip()
    if not sentence:
        return []
    if len(sentence) <= max_chars:
        return [sentence]

    clauses = re.split(r"(?<=[,;])\s+", sentence)
    if len(clauses) == 1:
        clauses = [c.strip() for c in _CONJUNCTION_SPLIT_RE.split(sentence) if c.strip()]

    phrases: list[str] = []
    buffer = ""
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        if len(clause) > max_chars:
            if buffer:
                phrases.append(buffer.strip())
                buffer = ""
            phrases.extend(_split_at_word_boundary(clause, max_chars))
            continue
        candidate = f"{buffer} {clause}".strip() if buffer else clause
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                phrases.append(buffer.strip())
            buffer = clause
    if buffer:
        phrases.append(buffer.strip())
    return phrases if phrases else _split_at_word_boundary(sentence, max_chars)


def split_tts_phrase_segments(
    text: str,
    *,
    max_chars: int = DEFAULT_PHRASE_MAX_CHARS,
    sentence_gap_ms: int = DEFAULT_PHRASE_GAP_MS,
    clause_gap_ms: int = DEFAULT_CLAUSE_GAP_MS,
) -> list[TtsPhraseSegment]:
    """
    Split response into short TTS chunks for low TTFA on the first segment.

    Sentence boundaries use ``sentence_gap_ms``; comma/conjunction splits within
    a sentence use the shorter ``clause_gap_ms``.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    raw_pieces: list[tuple[str, bool]] = []
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        ends_sentence = bool(sentence[-1] in ".!?")
        if len(sentence) <= max_chars:
            raw_pieces.append((sentence, ends_sentence))
            continue
        sub_parts = _subdivide_sentence(sentence, max_chars=max_chars)
        for index, part in enumerate(sub_parts):
            part_ends_sentence = ends_sentence and index == len(sub_parts) - 1
            raw_pieces.append((part, part_ends_sentence))

    if not raw_pieces:
        raw_pieces = [(cleaned, cleaned[-1] in ".!?")]

    segments: list[TtsPhraseSegment] = []
    for index, (piece, ends_sentence) in enumerate(raw_pieces):
        if index == len(raw_pieces) - 1:
            gap = 0
        elif ends_sentence:
            gap = sentence_gap_ms
        else:
            gap = clause_gap_ms
        segments.append(TtsPhraseSegment(piece, gap_after_ms=gap))
    return segments


def split_tts_phrases(text: str, *, max_chars: int = DEFAULT_PHRASE_MAX_CHARS) -> list[str]:
    """Split response text into TTS segments (text only; see ``split_tts_phrase_segments``)."""
    return [segment.text for segment in split_tts_phrase_segments(text, max_chars=max_chars)]


def estimate_max_duration_sec(
    text: str,
    *,
    ms_per_char: float = DEFAULT_MS_PER_CHAR,
    margin_factor: float = DEFAULT_MAX_DURATION_FACTOR,
    floor_sec: float = 1.0,
) -> float:
    """Generous upper bound for spoken duration from character count."""
    char_count = len((text or "").strip())
    if char_count == 0:
        return floor_sec
    return max(floor_sec, (char_count * ms_per_char / 1000.0) * margin_factor)


def pcm16_frame_rms(pcm: bytes, start_sample: int, frame_samples: int) -> float:
    end_byte = (start_sample + frame_samples) * 2
    chunk = pcm[start_sample * 2 : end_byte]
    if len(chunk) < 2:
        return 0.0
    n = len(chunk) // 2
    samples = struct.unpack(f"<{n}h", chunk)
    return math.sqrt(sum(s * s for s in samples) / n)


def trim_excess_pcm16(
    pcm: bytes,
    sample_rate: int,
    text: str,
    *,
    ms_per_char: float = DEFAULT_MS_PER_CHAR,
    margin_factor: float = DEFAULT_MAX_DURATION_FACTOR,
) -> bytes:
    """
    Trim audio that exceeds ~1.5× expected duration, preferring the last silence
    region before the limit (run-on / hallucination guard).
    """
    if not pcm or sample_rate <= 0:
        return pcm

    n_samples = len(pcm) // 2
    max_samples = int(
        sample_rate * estimate_max_duration_sec(
            text,
            ms_per_char=ms_per_char,
            margin_factor=margin_factor,
        )
    )
    if n_samples <= max_samples:
        return pcm

    frame_samples = max(1, sample_rate * FRAME_MS // 1000)
    min_silence_frames = max(1, sample_rate * MIN_SILENCE_MS // 1000 // frame_samples)
    search_start = max(0, max_samples - sample_rate * 3)
    silent_run = 0
    cut_sample: int | None = None

    for start in range(max_samples, search_start, -frame_samples):
        rms = pcm16_frame_rms(pcm, start, frame_samples)
        if rms < TRIM_SILENCE_RMS_THRESHOLD:
            silent_run += 1
            if silent_run >= min_silence_frames:
                cut_sample = start + frame_samples * silent_run
                break
        else:
            silent_run = 0

    if cut_sample is None:
        logger.info(
            "VOICE_TTS_TRIM skipped (no silence) text_chars=%s samples=%s max_samples=%s",
            len((text or "").strip()),
            n_samples,
            max_samples,
        )
        return pcm

    logger.info(
        "VOICE_TTS_TRIM text_chars=%s samples=%s max_samples=%s cut_sample=%s",
        len((text or "").strip()),
        n_samples,
        max_samples,
        cut_sample,
    )
    return pcm[: cut_sample * 2]


def pcm16_tail_rms(pcm: bytes, sample_rate: int, *, tail_ms: int = 50) -> float:
    """RMS of the last ``tail_ms`` milliseconds (for validation/tests)."""
    n_samples = len(pcm) // 2
    if n_samples == 0:
        return 0.0
    tail_samples = min(n_samples, max(1, sample_rate * tail_ms // 1000))
    start = n_samples - tail_samples
    return pcm16_frame_rms(pcm, start, tail_samples)


def apply_phrase_tail_fade(
    pcm: bytes,
    sample_rate: int,
    *,
    fade_ms: int = 5,
) -> bytes:
    """Short fade-out at phrase end (inter-phrase boundary, not full response)."""
    fade_samples = max(0, sample_rate * fade_ms // 1000)
    n = len(pcm) // 2
    if n == 0 or fade_samples == 0:
        return pcm
    fade_samples = min(fade_samples, n)
    samples = list(struct.unpack(f"<{n}h", pcm))
    for i in range(fade_samples):
        factor = (fade_samples - i) / fade_samples
        idx = n - fade_samples + i
        samples[idx] = int(samples[idx] * factor)
    return struct.pack(f"<{n}h", *samples)


def apply_fade_out(pcm: bytes, sample_rate: int, *, fade_ms: int = DEFAULT_FADE_OUT_MS) -> bytes:
    """Linear fade-out at the end so audio never stops abruptly."""
    fade_samples = max(0, sample_rate * fade_ms // 1000)
    n = len(pcm) // 2
    if n == 0 or fade_samples == 0:
        return pcm
    fade_samples = min(fade_samples, n)
    samples = list(struct.unpack(f"<{n}h", pcm))
    for i in range(fade_samples):
        factor = (fade_samples - i) / fade_samples
        idx = n - fade_samples + i
        samples[idx] = int(samples[idx] * factor)
    return struct.pack(f"<{n}h", *samples)


def pcm16_silence(sample_rate: int, duration_ms: int) -> bytes:
    n = max(0, sample_rate * duration_ms // 1000)
    return b"\x00\x00" * n


def _apply_fade(pcm: bytes, sample_rate: int, *, fade_ms: int = 5) -> bytes:
    """Short linear fade in/out to reduce clicks when concatenating phrases."""
    fade_samples = max(0, sample_rate * fade_ms // 1000)
    n = len(pcm) // 2
    if n == 0 or fade_samples == 0:
        return pcm
    fade_samples = min(fade_samples, n // 2)
    if fade_samples == 0:
        return pcm

    samples = list(struct.unpack(f"<{n}h", pcm))
    for i in range(fade_samples):
        factor_in = i / fade_samples
        factor_out = (fade_samples - i) / fade_samples
        samples[i] = int(samples[i] * factor_in)
        tail = n - fade_samples + i
        samples[tail] = int(samples[tail] * factor_out)
    return struct.pack(f"<{n}h", *samples)


def concatenate_pcm16_phrases(
    segments: list[bytes],
    sample_rate: int,
    *,
    gap_ms: int = DEFAULT_PHRASE_GAP_MS,
) -> bytes:
    """Join phrase PCM with uniform silence gaps and edge fades."""
    gaps = [gap_ms if index < len(segments) - 1 else 0 for index in range(len(segments))]
    return concatenate_pcm16_with_gaps(segments, sample_rate, gaps_after_ms=gaps)


def concatenate_pcm16_with_gaps(
    segments: list[bytes],
    sample_rate: int,
    *,
    gaps_after_ms: list[int],
) -> bytes:
    """Join phrase PCM with per-segment silence gaps and edge fades."""
    if not segments:
        return b""
    parts: list[bytes] = []
    for index, pcm in enumerate(segments):
        if not pcm:
            continue
        parts.append(_apply_fade(pcm, sample_rate))
        gap = gaps_after_ms[index] if index < len(gaps_after_ms) else 0
        if gap > 0 and index < len(segments) - 1:
            parts.append(pcm16_silence(sample_rate, gap))
    return b"".join(parts)


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()
