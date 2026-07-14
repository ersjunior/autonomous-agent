"""Tests — voice stream TTS phrase split and run-on trim (P2)."""

from __future__ import annotations

import io
import struct
import wave

import pytest

from agents.channels.voice.tts_stream import (
    DEFAULT_CLAUSE_GAP_MS,
    DEFAULT_PHRASE_GAP_MS,
    apply_fade_out,
    concatenate_pcm16_phrases,
    estimate_max_duration_sec,
    pcm16_silence,
    pcm16_tail_rms,
    split_tts_phrase_segments,
    split_tts_phrases,
    trim_excess_pcm16,
)

pytestmark = pytest.mark.unit

SAMPLE_RATE = 8000


def _tone_pcm(duration_ms: int, *, amplitude: int = 8000) -> bytes:
    n = SAMPLE_RATE * duration_ms // 1000
    return struct.pack(f"<{n}h", *([amplitude] * n))


def _wav_duration_sec(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def test_split_tts_phrases_on_sentences() -> None:
    text = "Olá! Estou aqui. Como posso ajudar?"
    phrases = split_tts_phrases(text)
    assert phrases == ["Olá!", "Estou aqui.", "Como posso ajudar?"]


def test_split_tts_phrases_subdivides_long_sentence() -> None:
    text = (
        "Você tem alguma dúvida sobre a ByteCell Academy, "
        "ou precisa de ajuda com algo relacionado ao seu curso?"
    )
    phrases = split_tts_phrases(text, max_chars=45)
    assert len(phrases) >= 2
    assert len(phrases[0]) <= 45
    assert "".join(phrases).replace(" ", "") == text.replace(" ", "")


def test_split_tts_phrase_segments_uses_clause_gap_within_sentence() -> None:
    text = (
        "A ByteCell Academy oferece cursos em diversas areas, "
        "incluindo Excel e Marketing Digital."
    )
    segments = split_tts_phrase_segments(text, max_chars=45)
    assert len(segments) >= 2
    assert len(segments[0].text) <= 45
    assert segments[0].gap_after_ms == DEFAULT_CLAUSE_GAP_MS
    assert segments[-1].gap_after_ms == 0


def test_split_tts_phrase_segments_sentence_gap_between_sentences() -> None:
    text = "Primeira frase curta. Segunda frase também curta."
    segments = split_tts_phrase_segments(text, max_chars=45)
    assert len(segments) == 2
    assert segments[0].gap_after_ms == DEFAULT_PHRASE_GAP_MS


def test_split_tts_phrases_empty() -> None:
    assert split_tts_phrases("   ") == []


def test_estimate_max_duration_scales_with_chars() -> None:
    short = estimate_max_duration_sec("Olá!")
    long = estimate_max_duration_sec("x" * 100)
    assert long > short


def test_trim_excess_pcm16_does_not_cut_normal_audio() -> None:
    text = "Frase curta."
    pcm = _tone_pcm(1200)
    trimmed = trim_excess_pcm16(pcm, SAMPLE_RATE, text)
    assert len(trimmed) == len(pcm)


def test_trim_excess_pcm16_skips_when_no_silence() -> None:
    text = "Frase curta."
    pcm = _tone_pcm(12000, amplitude=9000)
    trimmed = trim_excess_pcm16(pcm, SAMPLE_RATE, text, margin_factor=1.5)
    assert len(trimmed) == len(pcm)


def test_trim_excess_pcm16_cuts_at_silence_before_limit() -> None:
    text = "x" * 40
    speech = _tone_pcm(3000, amplitude=9000)
    silence = pcm16_silence(SAMPLE_RATE, 5000)
    pcm = speech + silence
    trimmed = trim_excess_pcm16(pcm, SAMPLE_RATE, text, margin_factor=1.5)
    assert len(trimmed) < len(pcm)


def test_concatenate_pcm16_phrases_adds_gap() -> None:
    a = _tone_pcm(100)
    b = _tone_pcm(100)
    combined = concatenate_pcm16_phrases([a, b], SAMPLE_RATE, gap_ms=150)
    gap_samples = SAMPLE_RATE * 150 // 1000
    expected = len(a) + gap_samples * 2 + len(b)
    assert abs(len(combined) - expected) <= SAMPLE_RATE // 50


def test_apply_fade_out_lowers_tail_rms() -> None:
    pcm = _tone_pcm(80, amplitude=9000)
    faded = apply_fade_out(pcm, SAMPLE_RATE, fade_ms=50)
    last_sample = struct.unpack("<h", faded[-2:])[0]
    assert abs(last_sample) < 50


@pytest.mark.asyncio
async def test_synthesize_voice_stream_wav_phrase_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.channels.voice.tts_stream_synth import synthesize_voice_stream_wav
    from app.core.config import settings

    calls: list[str] = []

    async def _fake_tts(text: str, *, sample_rate: int) -> bytes:
        calls.append(text)
        pcm = _tone_pcm(200)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    monkeypatch.setattr(settings, "voice_stream_tts_phrase_enabled", True)
    monkeypatch.setattr(
        "agents.channels.voice.tts_stream_synth.text_to_speech",
        _fake_tts,
    )

    text = "Primeira frase. Segunda frase."
    wav = await synthesize_voice_stream_wav(text, sample_rate=SAMPLE_RATE)
    assert len(calls) == 2
    assert _wav_duration_sec(wav) > 0.3


@pytest.mark.asyncio
async def test_synthesize_voice_stream_wav_single_call_when_phrase_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.channels.voice.tts_stream_synth import synthesize_voice_stream_wav
    from app.core.config import settings

    calls: list[str] = []

    async def _fake_tts(text: str, *, sample_rate: int) -> bytes:
        calls.append(text)
        pcm = _tone_pcm(300)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    monkeypatch.setattr(settings, "voice_stream_tts_phrase_enabled", False)
    monkeypatch.setattr(
        "agents.channels.voice.tts_stream_synth.text_to_speech",
        _fake_tts,
    )

    text = "Primeira frase. Segunda frase."
    await synthesize_voice_stream_wav(text, sample_rate=SAMPLE_RATE)
    assert calls == [text]
