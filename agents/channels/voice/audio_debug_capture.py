"""
Best-effort debug capture for voice stream TTS bisection (Coqui vs transmission).

Enable with ``VOICE_STREAM_DEBUG_SAVE_AUDIO=true`` (default off). Writes raw bytes only —
no inline analysis. Must never break or delay the voice stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import wave

from agents.channels.voice.mulaw_codec import MULAW_FRAME_BYTES, mulaw_to_pcm16
from app.core.config import settings

logger = logging.getLogger("app.voice_stream_audio_debug")

STREAM_DEBUG_SAMPLE_RATE = 8000


def debug_save_dir() -> Path:
    """Directory for captured artifacts (default: ``{voice_audio_root}/debug``)."""
    raw = (settings.voice_stream_debug_save_dir or "").strip()
    if raw:
        return Path(raw)
    return Path(settings.voice_audio_root) / "debug"


def pcm16_8k_to_wav(pcm: bytes) -> bytes:
    """Pack mono PCM int16 LE @ 8 kHz into a WAV container (stdlib only)."""
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(STREAM_DEBUG_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def frames_to_mulaw(frames: list[bytes]) -> bytes:
    """Concatenate Twilio-sized μ-law frames (post-chunk, pre-send)."""
    return b"".join(frames)


def _safe_filename_part(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in (value or "").strip()
    )
    return cleaned or "unknown"


def _write_capture_files_sync(
    dir_path: Path,
    stem: str,
    *,
    coqui_wav: bytes,
    mulaw_out: bytes,
    out_wav: bytes,
    meta: dict[str, Any],
) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{stem}_coqui_8k.wav").write_bytes(coqui_wav)
    (dir_path / f"{stem}_out.mulaw").write_bytes(mulaw_out)
    (dir_path / f"{stem}_out.wav").write_bytes(out_wav)
    (dir_path / f"{stem}_meta.json").write_bytes(
        json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
    )


async def save_voice_stream_debug_capture(
    *,
    call_sid: str,
    utterance_index: int,
    transcript: str,
    response_text: str,
    coqui_wav_bytes: bytes,
    mulaw_frames: list[bytes],
    extra: dict[str, Any] | None = None,
) -> None:
    """Write Coqui WAV, outbound μ-law, decoded WAV and meta JSON (best-effort)."""
    try:
        if not settings.voice_stream_debug_save_audio:
            return

        mulaw_out = frames_to_mulaw(mulaw_frames)
        out_wav = pcm16_8k_to_wav(mulaw_to_pcm16(mulaw_out))
        saved_at = datetime.now(timezone.utc).isoformat()
        safe_sid = _safe_filename_part(call_sid)
        stem = f"{safe_sid}_u{utterance_index}"
        dir_path = debug_save_dir()

        meta: dict[str, Any] = {
            "call_sid": call_sid,
            "utterance_index": utterance_index,
            "transcript": transcript,
            "response_text": response_text,
            "coqui_wav_bytes": len(coqui_wav_bytes),
            "mulaw_out_bytes": len(mulaw_out),
            "mulaw_frames_count": len(mulaw_frames),
            "mulaw_frame_bytes": MULAW_FRAME_BYTES,
            "out_wav_bytes": len(out_wav),
            "saved_at": saved_at,
            "debug_dir": str(dir_path),
        }
        if extra:
            meta.update(extra)

        await asyncio.to_thread(
            _write_capture_files_sync,
            dir_path,
            stem,
            coqui_wav=coqui_wav_bytes,
            mulaw_out=mulaw_out,
            out_wav=out_wav,
            meta=meta,
        )

        logger.info(
            "VOICE_STREAM_DEBUG_SAVE ok callSid=%s utterance=%s dir=%s stem=%s "
            "coqui_bytes=%s mulaw_bytes=%s frames=%s response_text=%r",
            call_sid,
            utterance_index,
            dir_path,
            stem,
            len(coqui_wav_bytes),
            len(mulaw_out),
            len(mulaw_frames),
            response_text,
        )
    except Exception as exc:
        logger.warning("VOICE_STREAM_DEBUG_SAVE failed (ignored): %s", exc)


def schedule_voice_stream_debug_capture(
    *,
    call_sid: str,
    utterance_index: int,
    transcript: str,
    response_text: str,
    coqui_wav_bytes: bytes,
    mulaw_frames: list[bytes],
    extra: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget capture task — does not block playback send."""
    try:
        if not settings.voice_stream_debug_save_audio:
            return

        logger.info(
            "VOICE_STREAM_DEBUG tts_text callSid=%s utterance=%s text=%r",
            call_sid,
            utterance_index,
            response_text,
        )

        asyncio.create_task(
            save_voice_stream_debug_capture(
                call_sid=call_sid,
                utterance_index=utterance_index,
                transcript=transcript,
                response_text=response_text,
                coqui_wav_bytes=coqui_wav_bytes,
                mulaw_frames=mulaw_frames,
                extra=extra,
            ),
            name=f"voice-debug-save-{call_sid}-u{utterance_index}",
        )
    except Exception as exc:
        logger.warning("VOICE_STREAM_DEBUG schedule failed (ignored): %s", exc)
