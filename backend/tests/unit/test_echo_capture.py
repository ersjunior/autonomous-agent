"""Unit tests — echo capture diagnostic (temporary F1 instrumentation)."""

from __future__ import annotations

import struct
import time

import pytest

from agents.channels.voice.echo_capture import (
    PlaybackEchoCapture,
    mulaw_frame_rms,
)
from agents.channels.voice.mulaw_codec import MULAW_FRAME_BYTES, pcm16_to_mulaw

pytestmark = pytest.mark.unit


def _loud_mulaw_frame() -> bytes:
    return pcm16_to_mulaw(struct.pack("<160h", *([5000] * 160)))[:MULAW_FRAME_BYTES]


def test_mulaw_frame_rms_silence_vs_loud() -> None:
    silence = pcm16_to_mulaw(struct.pack("<160h", *([0] * 160)))[:MULAW_FRAME_BYTES]
    loud = _loud_mulaw_frame()
    assert mulaw_frame_rms(loud) > mulaw_frame_rms(silence) * 10


def test_capture_segment_summary() -> None:
    cap = PlaybackEchoCapture(call_sid="CAtest")
    frame = _loud_mulaw_frame()
    cap.begin_segment(call_sid="CAtest", label="test")
    for _ in range(30):
        cap.record_outbound(frame)
        cap.record_inbound(frame)
    cap.finalize_segment(reason="test_end")
    assert cap._inbound_count == 30
    assert cap._outbound_count == 30
    assert len(cap._inbound_rms_values) == 30
    assert not cap.segment_active


def test_capture_never_raises_on_bad_input() -> None:
    cap = PlaybackEchoCapture(call_sid="CAtest")
    cap.begin_segment(call_sid="CAtest")
    cap.record_inbound(b"")
    cap.record_inbound(b"x" * 10)
    cap.record_outbound(b"")
    cap.finalize_segment()
    cap.finalize_call()
    assert not cap.segment_active


def test_capture_swallows_internal_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = PlaybackEchoCapture(call_sid="CAtest")
    cap.begin_segment(call_sid="CAtest")

    calls = 0
    original = mulaw_frame_rms

    def _fake_rms(frame: bytes) -> float:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated failure")
        return original(frame)

    monkeypatch.setattr("agents.channels.voice.echo_capture.mulaw_frame_rms", _fake_rms)
    cap.record_inbound(_loud_mulaw_frame())
    cap.record_inbound(_loud_mulaw_frame())
    cap.finalize_segment(reason="test")
    assert cap._inbound_count == 1


def test_capture_hot_path_is_fast() -> None:
    """Many frames should complete quickly without correlation lag search."""
    cap = PlaybackEchoCapture(call_sid="CAtest")
    frame = _loud_mulaw_frame()
    cap.begin_segment(call_sid="CAtest")
    start = time.perf_counter()
    for _ in range(500):
        cap.record_outbound(frame)
        cap.record_inbound(frame)
    elapsed = time.perf_counter() - start
    cap.finalize_segment(reason="perf")
    assert cap._inbound_count == 500
    assert elapsed < 0.5, f"500 frames took {elapsed:.2f}s — hot path too slow"
