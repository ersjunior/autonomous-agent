"""Stream voice TTS orchestration (phrase-by-phrase + trim + streaming send)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agents.channels.voice.mulaw_codec import (
    chunk_mulaw,
    pcm16_to_mulaw,
    wav_bytes_to_pcm16_mono,
)
from agents.channels.voice.tts_stt import text_to_speech
from agents.channels.voice.tts_stream import (
    DEFAULT_MAX_DURATION_FACTOR,
    DEFAULT_MS_PER_CHAR,
    TtsPhraseSegment,
    apply_fade_out,
    apply_phrase_tail_fade,
    concatenate_pcm16_with_gaps,
    pcm16_silence,
    pcm16_to_wav,
    split_tts_phrase_segments,
    trim_excess_pcm16,
)
from app.core.config import settings

logger = logging.getLogger("app.voice_stream_tts")

_FRAME_QUEUE_MAXSIZE = 512
_QUEUE_END = object()


@dataclass
class StreamTtsPlaybackResult:
    """Outcome of phrase-streamed TTS playback (for logging + debug capture)."""

    frames: list[bytes] = field(default_factory=list)
    wav_bytes: bytes = b""
    mulaw: bytes = b""
    phrase_count: int = 0
    tts_ms: float = 0.0
    ttfa_ms: float | None = None
    completed: bool = True


async def synthesize_phrase_pcm(
    phrase: str,
    *,
    sample_rate: int,
    ms_per_char: float,
    margin_factor: float,
) -> bytes:
    """Coqui WAV for one phrase → trimmed PCM16 mono."""
    wav_bytes = await text_to_speech(phrase, sample_rate=sample_rate)
    pcm = wav_bytes_to_pcm16_mono(wav_bytes, expected_rate=sample_rate)
    return trim_excess_pcm16(
        pcm,
        sample_rate,
        phrase,
        ms_per_char=ms_per_char,
        margin_factor=margin_factor,
    )


def gap_mulaw_frames(sample_rate: int, gap_ms: int) -> list[bytes]:
    gap_pcm = pcm16_silence(sample_rate, gap_ms)
    return chunk_mulaw(pcm16_to_mulaw(gap_pcm))


def _phrase_pcm_to_mulaw_frames(
    pcm: bytes,
    *,
    sample_rate: int,
    is_last_phrase: bool,
) -> list[bytes]:
    if is_last_phrase:
        pcm = apply_fade_out(pcm, sample_rate)
    else:
        pcm = apply_phrase_tail_fade(pcm, sample_rate, fade_ms=5)
    return chunk_mulaw(pcm16_to_mulaw(pcm))


def _resolve_phrase_segments(text: str) -> list[TtsPhraseSegment]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    max_chars = int(settings.voice_stream_tts_phrase_max_chars)
    if bool(settings.voice_stream_tts_phrase_enabled):
        return split_tts_phrase_segments(
            cleaned,
            max_chars=max_chars,
            sentence_gap_ms=int(settings.voice_stream_tts_phrase_gap_ms),
            clause_gap_ms=int(settings.voice_stream_tts_clause_gap_ms),
        )
    return [TtsPhraseSegment(cleaned, gap_after_ms=0)]


async def stream_phrase_tts_playback(
    text: str,
    *,
    sample_rate: int,
    on_frame: Callable[[bytes], Awaitable[bool]],
) -> StreamTtsPlaybackResult:
    """
    Synthesize phrase-by-phrase and send frames as each phrase completes (FIFO).

    Producer (synthesis) and consumer (on_frame) run concurrently so phrase N+1
    can synthesize while phrase N frames are transmitted.
    """
    tts_started = time.perf_counter()
    segments = _resolve_phrase_segments(text)
    if not segments:
        return StreamTtsPlaybackResult()

    ms_per_char = float(settings.voice_stream_tts_ms_per_char)
    margin_factor = float(settings.voice_stream_tts_max_duration_factor)

    frame_queue: asyncio.Queue[bytes | object] = asyncio.Queue(maxsize=_FRAME_QUEUE_MAXSIZE)
    phrase_pcms: list[bytes] = []
    phrase_gaps: list[int] = []
    synth_errors: list[str] = []
    producer_phrase_count = 0

    async def producer() -> None:
        nonlocal producer_phrase_count
        for index, segment in enumerate(segments):
            phrase = segment.text
            try:
                pcm = await synthesize_phrase_pcm(
                    phrase,
                    sample_rate=sample_rate,
                    ms_per_char=ms_per_char,
                    margin_factor=margin_factor,
                )
                phrase_pcms.append(pcm)
                phrase_gaps.append(segment.gap_after_ms)
                producer_phrase_count += 1

                if index > 0:
                    gap_ms = segments[index - 1].gap_after_ms
                    if gap_ms > 0:
                        for frame in gap_mulaw_frames(sample_rate, gap_ms):
                            await frame_queue.put(frame)

                is_last = index == len(segments) - 1
                for frame in _phrase_pcm_to_mulaw_frames(
                    pcm,
                    sample_rate=sample_rate,
                    is_last_phrase=is_last,
                ):
                    await frame_queue.put(frame)
            except Exception as exc:
                synth_errors.append(str(exc))
                logger.warning(
                    "VOICE_TTS_PHRASE synth failed phrase=%s/%s text=%r: %s",
                    index + 1,
                    len(segments),
                    phrase[:80],
                    exc,
                )
        await frame_queue.put(_QUEUE_END)

    result = StreamTtsPlaybackResult(phrase_count=len(segments))
    ttfa_ms: float | None = None
    completed = True

    async def consumer() -> None:
        nonlocal ttfa_ms, completed
        while True:
            item = await frame_queue.get()
            if item is _QUEUE_END:
                break
            frame = item
            assert isinstance(frame, bytes)
            if ttfa_ms is None:
                ttfa_ms = (time.perf_counter() - tts_started) * 1000
            result.frames.append(frame)
            if not await on_frame(frame):
                completed = False
                break

    producer_task = asyncio.create_task(producer(), name="voice-tts-phrase-producer")
    consumer_task = asyncio.create_task(consumer(), name="voice-tts-phrase-consumer")
    await consumer_task
    if not completed:
        producer_task.cancel()
        try:
            await producer_task
        except asyncio.CancelledError:
            pass
    else:
        await producer_task

    if not producer_task.cancelled():
        result.phrase_count = producer_phrase_count or len(segments)

    result.tts_ms = (time.perf_counter() - tts_started) * 1000
    result.ttfa_ms = ttfa_ms
    result.completed = completed and not synth_errors
    result.mulaw = b"".join(result.frames)

    if phrase_pcms:
        if len(phrase_pcms) == 1:
            combined_pcm = apply_fade_out(phrase_pcms[0], sample_rate)
        else:
            combined_pcm = concatenate_pcm16_with_gaps(
                phrase_pcms,
                sample_rate,
                gaps_after_ms=phrase_gaps,
            )
            combined_pcm = apply_fade_out(combined_pcm, sample_rate)
        combined_pcm = trim_excess_pcm16(
            combined_pcm,
            sample_rate,
            text,
            ms_per_char=ms_per_char,
            margin_factor=margin_factor,
        )
        result.wav_bytes = pcm16_to_wav(combined_pcm, sample_rate)
    elif result.mulaw:
        from agents.channels.voice.mulaw_codec import mulaw_to_pcm16

        result.wav_bytes = pcm16_to_wav(mulaw_to_pcm16(result.mulaw), sample_rate)

    logger.info(
        "VOICE_TTS_STREAM phrases=%s frames=%s tts_ms=%.0f ttfa_ms=%s errors=%s",
        result.phrase_count,
        len(result.frames),
        result.tts_ms,
        f"{result.ttfa_ms:.0f}" if result.ttfa_ms is not None else "?",
        len(synth_errors),
    )
    return result


async def synthesize_voice_stream_wav(
    text: str,
    *,
    sample_rate: int,
) -> bytes:
    """
    Batch telephony WAV (record/debug/tests). Stream path uses ``stream_phrase_tts_playback``.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return pcm16_to_wav(b"", sample_rate)

    ms_per_char = float(settings.voice_stream_tts_ms_per_char)
    margin_factor = float(settings.voice_stream_tts_max_duration_factor)
    segments = _resolve_phrase_segments(cleaned)

    if len(segments) > 1:
        logger.info(
            "VOICE_TTS_PHRASES count=%s chars=%s phrases=%r",
            len(segments),
            len(cleaned),
            [len(s.text) for s in segments],
        )

    pcm_segments: list[bytes] = []
    for segment in segments:
        pcm_segments.append(
            await synthesize_phrase_pcm(
                segment.text,
                sample_rate=sample_rate,
                ms_per_char=ms_per_char,
                margin_factor=margin_factor,
            )
        )

    if len(pcm_segments) == 1:
        combined = pcm_segments[0]
    else:
        combined = concatenate_pcm16_with_gaps(
            pcm_segments,
            sample_rate,
            gaps_after_ms=[s.gap_after_ms for s in segments],
        )

    combined = trim_excess_pcm16(
        combined,
        sample_rate,
        cleaned,
        ms_per_char=ms_per_char,
        margin_factor=margin_factor,
    )
    combined = apply_fade_out(combined, sample_rate)
    return pcm16_to_wav(combined, sample_rate)
