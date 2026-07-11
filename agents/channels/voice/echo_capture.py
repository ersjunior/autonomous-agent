"""
Diagnostic capture: inbound vs outbound RMS during agent playback (echo / AEC study).

Enable with ``VOICE_STREAM_ECHO_DEBUG_CAPTURE=true`` (default off). Best-effort only — must never break
the voice stream when disabled.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from agents.channels.voice.mulaw_codec import MULAW_FRAME_BYTES, _mulaw_to_linear

logger = logging.getLogger("agents.channels.voice.echo_capture")

FRAME_MS = 20
LOG_EVERY_N_FRAMES = 25


def mulaw_frame_rms(frame_mulaw: bytes) -> float:
    """RMS of one μ-law frame (8 kHz mono) — O(n) scalar loop, no allocations."""
    n = len(frame_mulaw)
    if n == 0:
        return 0.0
    sum_sq = 0.0
    for byte in frame_mulaw:
        sample = _mulaw_to_linear(byte)
        sum_sq += sample * sample
    return math.sqrt(sum_sq / n)


def _rms_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    n = len(values)
    sorted_vals = sorted(values)
    return {
        "mean": sum(values) / n,
        "median": sorted_vals[n // 2],
        "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
    }


@dataclass
class PlaybackEchoCapture:
    """
    Records per-frame inbound/outbound RMS during agent playback segments.

    Logs with prefix ``ECHO_CAPTURE`` (grep-friendly). No correlation/lag on hot path.
    """

    call_sid: str | None = None
    frame_ms: int = FRAME_MS
    _segment_id: int = 0
    _inbound_count: int = 0
    _outbound_count: int = 0
    _inbound_rms_values: list[float] = field(default_factory=list)
    _outbound_rms_values: list[float] = field(default_factory=list)
    _last_outbound_rms: float = 0.0
    _segment_active: bool = False

    @property
    def segment_active(self) -> bool:
        return self._segment_active

    def begin_segment(self, *, call_sid: str | None, label: str = "agent") -> None:
        try:
            if self._segment_active:
                self.finalize_segment(reason="new_segment")
            self._segment_id += 1
            self._segment_active = True
            self.call_sid = call_sid
            self._inbound_count = 0
            self._outbound_count = 0
            self._inbound_rms_values.clear()
            self._outbound_rms_values.clear()
            self._last_outbound_rms = 0.0
            logger.info(
                "ECHO_CAPTURE segment_begin id=%s callSid=%s label=%s",
                self._segment_id,
                call_sid or "?",
                label,
            )
        except Exception as exc:
            logger.warning("ECHO_CAPTURE begin_segment failed (ignored): %s", exc)

    def record_outbound(self, frame_mulaw: bytes, *, ts: float | None = None) -> None:
        try:
            if not self._segment_active or len(frame_mulaw) != MULAW_FRAME_BYTES:
                return
            out_rms = mulaw_frame_rms(frame_mulaw)
            self._outbound_count += 1
            self._outbound_rms_values.append(out_rms)
            self._last_outbound_rms = out_rms
        except Exception as exc:
            logger.warning("ECHO_CAPTURE record_outbound failed (ignored): %s", exc)

    def record_inbound(self, frame_mulaw: bytes, *, ts: float | None = None) -> None:
        try:
            if not self._segment_active or len(frame_mulaw) != MULAW_FRAME_BYTES:
                return
            ts = ts if ts is not None else time.perf_counter()
            in_rms = mulaw_frame_rms(frame_mulaw)
            self._inbound_count += 1
            self._inbound_rms_values.append(in_rms)

            idx = self._inbound_count
            if idx == 1 or idx % LOG_EVERY_N_FRAMES == 0:
                logger.info(
                    "ECHO_CAPTURE frame segment=%s callSid=%s idx=%s ts=%.3f "
                    "in_rms=%.1f out_rms=%.1f",
                    self._segment_id,
                    self.call_sid or "?",
                    idx,
                    ts,
                    in_rms,
                    self._last_outbound_rms,
                )
        except Exception as exc:
            logger.warning("ECHO_CAPTURE record_inbound failed (ignored): %s", exc)

    def finalize_segment(self, *, reason: str = "playback_end") -> None:
        try:
            if not self._segment_active:
                return
            self._segment_active = False

            if not self._inbound_rms_values:
                logger.info(
                    "ECHO_CAPTURE segment_end id=%s callSid=%s reason=%s "
                    "inbound_frames=0 outbound_frames=%s",
                    self._segment_id,
                    self.call_sid or "?",
                    reason,
                    self._outbound_count,
                )
                return

            in_stats = _rms_stats(self._inbound_rms_values)
            out_stats = _rms_stats(self._outbound_rms_values)

            logger.info(
                "ECHO_CAPTURE_SUMMARY segment=%s callSid=%s reason=%s "
                "inbound_frames=%s outbound_frames=%s "
                "in_rms_mean=%.1f in_rms_median=%.1f in_rms_p95=%.1f "
                "in_rms_min=%.1f in_rms_max=%.1f out_rms_mean=%.1f",
                self._segment_id,
                self.call_sid or "?",
                reason,
                self._inbound_count,
                self._outbound_count,
                in_stats["mean"],
                in_stats["median"],
                in_stats["p95"],
                in_stats["min"],
                in_stats["max"],
                out_stats["mean"],
            )
        except Exception as exc:
            logger.warning("ECHO_CAPTURE finalize_segment failed (ignored): %s", exc)
            self._segment_active = False

    def finalize_call(self) -> None:
        try:
            if self._segment_active:
                self.finalize_segment(reason="call_end")
        except Exception as exc:
            logger.warning("ECHO_CAPTURE finalize_call failed (ignored): %s", exc)
