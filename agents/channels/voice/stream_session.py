"""Twilio Media Streams WebSocket session handler (Fase A–D1: transport + VAD + STT + agent + TTS)."""

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
from agents.channels.voice.mulaw_codec import (
    INTRO_FRAMES,
    MULAW_FRAME_BYTES,
    chunk_mulaw,
    pcm16_to_mulaw,
    wav_bytes_to_pcm16_mono,
)
from agents.channels.voice.tts_stt import speech_to_text, text_to_speech
from app.core.config import settings

logger = logging.getLogger(__name__)

MEDIA_LOG_EVERY_N = 50
STREAM_TTS_SAMPLE_RATE = 8000
AGENT_RESPONSE_MARK = "agent_response_done"
VOICE_STREAM_AGENT_FALLBACK = "Desculpe, não consegui processar agora."


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


async def _run_voice_agent_for_stream(
    *,
    from_number: str,
    transcript: str,
    call_sid: str | None,
) -> str:
    """
    Same agent path as record mode (``process_voice_inbound_turn`` → ``run_voice_agent_turn``).

    First argument is ``session`` (AsyncSession positional) — not ``db=``.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.voice_turn_processor import run_voice_agent_turn

    async with AsyncSessionLocal() as session:
        return await run_voice_agent_turn(
            session,
            from_number=from_number,
            transcript=transcript,
            call_sid=call_sid,
        )


async def _synthesize_stream_mulaw_frames(response_text: str) -> list[bytes]:
    """Coqui @ 8 kHz WAV → PCM16 → μ-law frames (no backend downsample)."""
    wav_bytes = await text_to_speech(
        response_text,
        sample_rate=STREAM_TTS_SAMPLE_RATE,
    )
    pcm16 = wav_bytes_to_pcm16_mono(
        wav_bytes,
        expected_rate=STREAM_TTS_SAMPLE_RATE,
    )
    mulaw = pcm16_to_mulaw(pcm16)
    return chunk_mulaw(mulaw)


async def _process_utterance_turn(
    result: UtteranceClosed,
    *,
    call_sid: str | None,
    stream_sid: str | None,
    websocket: WebSocket,
    response_lock: asyncio.Lock,
) -> None:
    """
    Fase C+D1: STT (parallel-safe) → agent → TTS → μ-law outbound (serialized per call).
    """
    wav_bytes = pcm16_16k_to_wav(result.pcm16_16k)
    stt_started = time.perf_counter()
    try:
        transcript = (
            await speech_to_text(
                wav_bytes,
                language="pt",
                filename="utterance.wav",
                content_type="audio/wav",
            )
        ).strip()
    except Exception as exc:
        stt_ms = (time.perf_counter() - stt_started) * 1000
        logger.error(
            "Voice stream STT failed utterance #%s callSid=%s duration_ms=%s stt_ms=%s: %s",
            result.index,
            call_sid or "?",
            result.duration_ms,
            stt_ms,
            exc,
        )
        return

    stt_ms = (time.perf_counter() - stt_started) * 1000
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

    if not transcript:
        logger.info(
            "Voice stream utterance #%s callSid=%s empty transcript — skipping agent",
            result.index,
            call_sid or "?",
        )
        return

    sid = (call_sid or "").strip()
    if sid:
        from app.services.voice_call_state import get_call_customer_number, reset_silence_stage

        from_number = (get_call_customer_number(sid) or "").strip()
        if from_number:
            reset_silence_stage(sid, from_number=from_number)
        else:
            logger.warning(
                "Voice stream agent skip: no from_number for callSid=%s utterance #%s",
                sid,
                result.index,
            )
            return
    else:
        logger.warning(
            "Voice stream agent skip: missing callSid utterance #%s",
            result.index,
        )
        return

    if not (stream_sid or "").strip():
        logger.error(
            "Voice stream agent skip: missing streamSid callSid=%s utterance #%s",
            sid,
            result.index,
        )
        return

    async with response_lock:
        agent_started = time.perf_counter()
        response_text = ""
        try:
            response_text = (
                await _run_voice_agent_for_stream(
                    from_number=from_number,
                    transcript=transcript,
                    call_sid=sid or None,
                )
            ).strip()
        except Exception as exc:
            agent_ms = (time.perf_counter() - agent_started) * 1000
            logger.error(
                "Voice stream agent failed utterance #%s callSid=%s agent_ms=%s: %s",
                result.index,
                sid,
                agent_ms,
                exc,
            )
            response_text = VOICE_STREAM_AGENT_FALLBACK

        agent_ms = (time.perf_counter() - agent_started) * 1000
        if not response_text:
            response_text = VOICE_STREAM_AGENT_FALLBACK

        tts_started = time.perf_counter()
        try:
            frames = await _synthesize_stream_mulaw_frames(response_text)
        except Exception as exc:
            tts_ms = (time.perf_counter() - tts_started) * 1000
            logger.error(
                "Voice stream TTS failed utterance #%s callSid=%s agent_ms=%s tts_ms=%s: %s",
                result.index,
                sid,
                agent_ms,
                tts_ms,
                exc,
            )
            return

        tts_ms = (time.perf_counter() - tts_started) * 1000
        try:
            await _send_mulaw_frames(
                websocket,
                stream_sid=stream_sid,
                frames=frames,
                label="agent",
            )
            await _send_mark(
                websocket,
                stream_sid=stream_sid,
                name=AGENT_RESPONSE_MARK,
            )
        except Exception as exc:
            logger.error(
                "Voice stream outbound audio failed utterance #%s callSid=%s: %s",
                result.index,
                sid,
                exc,
            )
            return

        logger.info(
            "Voice stream agent response callSid=%s utterance#%s agent_ms=%s tts_ms=%s "
            "audio_frames=%s response=%r",
            sid,
            result.index,
            agent_ms,
            tts_ms,
            len(frames),
            response_text,
        )


async def _schedule_utterance_transcription(
    result: UtteranceClosed,
    *,
    call_sid: str | None,
    stream_sid: str | None,
    websocket: WebSocket,
    response_lock: asyncio.Lock,
    stt_tasks: set[asyncio.Task[None]],
) -> None:
    """
    Log utterance boundary and run STT → agent → TTS in a background task.

    ``response_lock`` serializes agent/TTS/send per call; receive loop stays free.
    """
    logger.info(
        "Voice stream utterance closed #%s duration_ms=%s bytes=%s callSid=%s",
        result.index,
        result.duration_ms,
        len(result.pcm16_16k),
        call_sid or "?",
    )

    async def _run_turn() -> None:
        try:
            await _process_utterance_turn(
                result,
                call_sid=call_sid,
                stream_sid=stream_sid,
                websocket=websocket,
                response_lock=response_lock,
            )
        finally:
            current = asyncio.current_task()
            if current is not None:
                stt_tasks.discard(current)

    task = asyncio.create_task(_run_turn())
    stt_tasks.add(task)


async def _finalize_session(
    session: VoiceStreamSession | None,
    *,
    call_sid: str | None,
    stream_sid: str | None,
    websocket: WebSocket,
    response_lock: asyncio.Lock,
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
            stream_sid=stream_sid,
            websocket=websocket,
            response_lock=response_lock,
            stt_tasks=stt_tasks,
        )

    pending = [t for t in stt_tasks if not t.done()]
    if pending:
        logger.info(
            "Voice stream teardown callSid=%s with %s pending turn task(s)",
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
    Fase C: utterance → STT (background).
    Fase D1: STT → agent → TTS 8 kHz → μ-law outbound (serialized per call).
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
    response_lock = asyncio.Lock()

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
                                stream_sid=stream_sid,
                                websocket=websocket,
                                response_lock=response_lock,
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
                    stream_sid=stream_sid,
                    websocket=websocket,
                    response_lock=response_lock,
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
        await _finalize_session(
            session,
            call_sid=call_sid,
            stream_sid=stream_sid,
            websocket=websocket,
            response_lock=response_lock,
            stt_tasks=stt_tasks,
        )
    except Exception:
        logger.exception(
            "Voice stream handler error callSid=%s streamSid=%s",
            call_sid or "?",
            stream_sid or "?",
        )
        await _finalize_session(
            session,
            call_sid=call_sid,
            stream_sid=stream_sid,
            websocket=websocket,
            response_lock=response_lock,
            stt_tasks=stt_tasks,
        )
        raise
