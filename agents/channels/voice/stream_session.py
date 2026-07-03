"""Twilio Media Streams WebSocket session handler (Fase A transport + Fase B VAD + Fase C STT)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from agents.channels.voice.audio_pipeline import (
    UtteranceClosed,
    VoiceStreamSession,
    create_voice_stream_session_from_settings,
    pcm16_16k_to_wav,
)
from agents.channels.voice.mulaw_codec import INTRO_FRAMES, MULAW_FRAME_BYTES
from agents.channels.voice.tts_stt import speech_to_text
from app.core.config import settings

logger = logging.getLogger(__name__)

MEDIA_LOG_EVERY_N = 50


def _log_unknown_call_sid(call_sid: str) -> None:
    """Light validation: warn if callSid was not registered on inbound webhook."""
    from app.services.voice_call_state import get_voice_call_state

    sid = (call_sid or "").strip()
    if not sid:
        return
    state = get_voice_call_state(sid)
    if state is None or not (state.get("from_number") or "").strip():
        logger.warning(
            "Voice stream start with unregistered callSid=%s (no voice_call_state)",
            sid,
        )


async def _transcribe_utterance(
    result: UtteranceClosed,
    *,
    call_sid: str | None,
) -> None:
    """Fase C: PCM utterance → WAV → faster-whisper → diagnostic log (no agent yet)."""
    wav_bytes = pcm16_16k_to_wav(result.pcm16_16k)
    started = time.perf_counter()
    try:
        transcript = (
            await speech_to_text(
                wav_bytes,
                language="pt",
                filename="utterance.wav",
                content_type="audio/wav",
            )
        ).strip()
        stt_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "Voice stream STT utterance #%s callSid=%s duration_ms=%s wav_bytes=%s "
            "stt_ms=%s transcript_len=%s transcript=%r",
            result.index,
            call_sid or "?",
            result.duration_ms,
            len(wav_bytes),
            stt_ms,
            len(transcript),
            transcript,
        )
    except Exception as exc:
        stt_ms = (time.perf_counter() - started) * 1000
        logger.error(
            "Voice stream STT failed utterance #%s callSid=%s duration_ms=%s stt_ms=%s: %s",
            result.index,
            call_sid or "?",
            result.duration_ms,
            stt_ms,
            exc,
        )


async def _schedule_utterance_transcription(
    result: UtteranceClosed,
    *,
    call_sid: str | None,
    stt_tasks: set[asyncio.Task[None]],
) -> None:
    """
    Log utterance boundary and run STT in a background task (non-blocking receive loop).

    Fase D extension point: add per-call_sid asyncio.Queue or Lock here to serialize
    agent turn processing after STT completes (parallel STT + log is OK for Fase C).
    """
    logger.info(
        "Voice stream utterance closed #%s duration_ms=%s bytes=%s callSid=%s",
        result.index,
        result.duration_ms,
        len(result.pcm16_16k),
        call_sid or "?",
    )

    async def _run_stt() -> None:
        try:
            await _transcribe_utterance(result, call_sid=call_sid)
        finally:
            current = asyncio.current_task()
            if current is not None:
                stt_tasks.discard(current)

    task = asyncio.create_task(_run_stt())
    stt_tasks.add(task)


async def _finalize_session(
    session: VoiceStreamSession | None,
    *,
    call_sid: str | None,
    stt_tasks: set[asyncio.Task[None]],
) -> None:
    if session is None:
        return
    flushed = session.flush()
    if flushed is not None:
        logger.info(
            "Voice stream utterance flushed on teardown #%s duration_ms=%s callSid=%s",
            flushed.index,
            flushed.duration_ms,
            call_sid or "?",
        )
        await _schedule_utterance_transcription(
            flushed,
            call_sid=call_sid,
            stt_tasks=stt_tasks,
        )

    pending = [t for t in stt_tasks if not t.done()]
    if pending:
        logger.info(
            "Voice stream teardown callSid=%s with %s pending STT task(s)",
            call_sid or "?",
            len(pending),
        )


async def _send_mulaw_frames(
    websocket: WebSocket,
    *,
    stream_sid: str,
    frames: list[bytes],
    label: str,
) -> None:
    """Send outbound μ-law frames to Twilio (base64 in JSON media events)."""
    for index, frame in enumerate(frames, start=1):
        outbound: dict[str, Any] = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(frame).decode("ascii")},
        }
        await websocket.send_text(json.dumps(outbound))
        if index == 1 or index == len(frames) or index % 10 == 0:
            logger.info(
                "Voice stream %s: frame %s/%s (%s bytes μ-law)",
                label,
                index,
                len(frames),
                len(frame),
            )


async def _send_mark(websocket: WebSocket, *, stream_sid: str, name: str) -> None:
    """Optional mark — Twilio echoes it when playback catches up."""
    payload = {
        "event": "mark",
        "streamSid": stream_sid,
        "mark": {"name": name},
    }
    await websocket.send_text(json.dumps(payload))
    logger.info("Voice stream mark sent name=%s streamSid=%s", name, stream_sid)


async def handle_voice_media_stream(websocket: WebSocket) -> None:
    """
    Handle bidirectional Twilio Media Stream.

    Fase A: log + intro beep + optional echo.
    Fase B: inbound μ-law → VAD utterance detection.
    Fase C: utterance → STT (background) → diagnostic log.
    """
    await websocket.accept()
    logger.info("Voice Media Stream WebSocket accepted")

    stream_sid: str | None = None
    call_sid: str | None = None
    session: VoiceStreamSession | None = None
    echo_enabled = bool(settings.voice_stream_echo_debug)
    media_in_count = 0
    media_out_count = 0
    stt_tasks: set[asyncio.Task[None]] = set()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Voice stream invalid JSON: %r", raw[:200])
                continue

            event = (message.get("event") or "").strip()
            sid_in_msg = (message.get("streamSid") or "").strip()

            if event == "connected":
                logger.info(
                    "Voice stream connected protocol=%s version=%s",
                    message.get("protocol"),
                    message.get("version"),
                )
                continue

            if event == "start":
                start_block = message.get("start") or {}
                stream_sid = (
                    sid_in_msg
                    or (start_block.get("streamSid") or "").strip()
                    or None
                )
                call_sid = (start_block.get("callSid") or "").strip() or None
                try:
                    session = create_voice_stream_session_from_settings(
                        call_sid=call_sid,
                        stream_sid=stream_sid,
                        settings=settings,
                    )
                except (ImportError, ModuleNotFoundError) as exc:
                    logger.error(
                        "Voice stream webrtcvad ausente; sessão de stream não pode iniciar "
                        "callSid=%s streamSid=%s: %s",
                        call_sid or "?",
                        stream_sid or "?",
                        exc,
                    )
                    break
                logger.info(
                    "Voice stream start streamSid=%s callSid=%s tracks=%s echo_debug=%s",
                    stream_sid,
                    call_sid or "?",
                    start_block.get("tracks"),
                    echo_enabled,
                )
                if call_sid:
                    _log_unknown_call_sid(call_sid)
                if not stream_sid:
                    logger.error("Voice stream start without streamSid — cannot send audio")
                    continue

                logger.info(
                    "Voice stream sending intro beep (%s frames, %s bytes/frame)",
                    len(INTRO_FRAMES),
                    MULAW_FRAME_BYTES,
                )
                await _send_mulaw_frames(
                    websocket,
                    stream_sid=stream_sid,
                    frames=INTRO_FRAMES,
                    label="intro",
                )
                await _send_mark(websocket, stream_sid=stream_sid, name="intro_done")
                # Anti-echo gate: enable VAD after outbound intro is queued.
                # Twilio may echo intro_done mark when playback completes (handled below).
                if session is not None:
                    session.listening = True
                    logger.info(
                        "Voice stream listening enabled (post-intro) callSid=%s",
                        call_sid or "?",
                    )
                continue

            if event == "media":
                media_in_count += 1
                media_block = message.get("media") or {}
                payload_b64 = (media_block.get("payload") or "").strip()
                track = (media_block.get("track") or "inbound").strip().lower()
                if media_in_count <= 3 or media_in_count % MEDIA_LOG_EVERY_N == 0:
                    logger.info(
                        "Voice stream media IN #%s track=%s payload_len=%s callSid=%s",
                        media_in_count,
                        track,
                        len(payload_b64),
                        call_sid or "?",
                    )

                if track == "inbound" and payload_b64 and session is not None:
                    try:
                        frame_mulaw = base64.b64decode(payload_b64)
                    except Exception:
                        logger.warning(
                            "Voice stream invalid media payload callSid=%s",
                            call_sid or "?",
                        )
                        frame_mulaw = b""
                    if frame_mulaw:
                        closed = session.feed_mulaw_frame(frame_mulaw)
                        if closed is not None:
                            await _schedule_utterance_transcription(
                                closed,
                                call_sid=call_sid,
                                stt_tasks=stt_tasks,
                            )

                if echo_enabled and stream_sid and payload_b64:
                    outbound = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload_b64},
                    }
                    await websocket.send_text(json.dumps(outbound))
                    media_out_count += 1
                    if media_out_count <= 3 or media_out_count % MEDIA_LOG_EVERY_N == 0:
                        logger.info(
                            "Voice stream media OUT (echo) #%s callSid=%s",
                            media_out_count,
                            call_sid or "?",
                        )
                continue

            if event == "mark":
                mark_name = (message.get("mark") or {}).get("name", "?")
                logger.info(
                    "Voice stream mark received name=%s streamSid=%s callSid=%s",
                    mark_name,
                    sid_in_msg or stream_sid,
                    call_sid or "?",
                )
                if mark_name == "intro_done" and session is not None and not session.listening:
                    session.listening = True
                    logger.info(
                        "Voice stream listening enabled (intro_done mark) callSid=%s",
                        call_sid or "?",
                    )
                continue

            if event == "stop":
                logger.info(
                    "Voice stream stop streamSid=%s callSid=%s media_in=%s media_out_echo=%s",
                    sid_in_msg or stream_sid,
                    call_sid or "?",
                    media_in_count,
                    media_out_count,
                )
                await _finalize_session(
                    session,
                    call_sid=call_sid,
                    stt_tasks=stt_tasks,
                )
                break

            logger.info(
                "Voice stream unhandled event=%s keys=%s callSid=%s",
                event,
                list(message.keys()),
                call_sid or "?",
            )

    except WebSocketDisconnect:
        logger.info(
            "Voice stream WebSocket disconnected callSid=%s streamSid=%s "
            "media_in=%s media_out_echo=%s",
            call_sid or "?",
            stream_sid or "?",
            media_in_count,
            media_out_count,
        )
        await _finalize_session(session, call_sid=call_sid, stt_tasks=stt_tasks)
    except Exception:
        logger.exception(
            "Voice stream handler error callSid=%s streamSid=%s",
            call_sid or "?",
            stream_sid or "?",
        )
        await _finalize_session(session, call_sid=call_sid, stt_tasks=stt_tasks)
        raise
