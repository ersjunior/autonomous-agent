"""Twilio Media Streams WebSocket session handler (Fase A–D2a: transport + VAD + FIFO worker + hangup)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
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
    MULAW_SILENCE_BYTE,
    wav_bytes_to_pcm16_mono,
)
from agents.channels.voice.audio_debug_capture import schedule_voice_stream_debug_capture
from agents.channels.voice.echo_capture import PlaybackEchoCapture
from agents.channels.voice.tts_stream_synth import (
    StreamTtsPlaybackResult,
    stream_phrase_tts_playback,
    synthesize_voice_stream_wav,
)
from agents.channels.voice.tts_stt import speech_to_text
from agents.channels.voice.twilio_voice_client import end_twilio_call
from app.core.config import settings

logger = logging.getLogger(__name__)

MEDIA_LOG_EVERY_N = 50
STREAM_TTS_SAMPLE_RATE = 8000
AGENT_RESPONSE_MARK = "agent_response_done"
FAREWELL_DONE_MARK = "farewell_done"
VOICE_STREAM_AGENT_FALLBACK = "Desculpe, não consegui processar agora."
UTTERANCE_QUEUE_MAXSIZE = 32
_STREAM_QUEUE_SENTINEL = object()


@dataclass(frozen=True, slots=True)
class StreamTtsResult:
    """Coqui WAV @ 8 kHz plus encoded μ-law (raw + Twilio frames)."""

    wav_bytes: bytes
    mulaw: bytes
    frames: list[bytes]


@dataclass
class StreamCallControl:
    """Shared WS session state (marks, hangup, barge-in). Per-turn outputs stay local."""

    mark_events: dict[str, asyncio.Event] = field(default_factory=dict)
    call_ended: bool = False
    agent_speaking: bool = False
    playback_interrupt: asyncio.Event = field(default_factory=asyncio.Event)
    _barge_in_clear_sent: bool = False
    echo_capture: PlaybackEchoCapture | None = None

    def begin_agent_playback(self) -> None:
        """Mark agent audio in-flight (send + Twilio buffer until mark echo)."""
        self.playback_interrupt.clear()
        self._barge_in_clear_sent = False
        self.agent_speaking = True

    def end_agent_playback(self) -> None:
        self.agent_speaking = False

    def request_playback_interrupt(self) -> bool:
        """
        Signal worker to abort playback. Returns True only on the first request
        (caller should send Twilio ``clear`` once per interruption).
        """
        self.playback_interrupt.set()
        if self._barge_in_clear_sent:
            return False
        self._barge_in_clear_sent = True
        return True


class StreamUtteranceWorker:
    """
    FIFO serial processor for one call: STT → agent → TTS → send (one utterance at a time).

    The WebSocket receive loop only enqueues; this worker runs in a background task.
    """

    def __init__(
        self,
        *,
        call_sid: str | None,
        stream_sid: str | None,
        websocket: WebSocket,
        control: StreamCallControl,
        maxsize: int = UTTERANCE_QUEUE_MAXSIZE,
    ) -> None:
        self._call_sid = call_sid
        self._stream_sid = stream_sid
        self._websocket = websocket
        self._control = control
        self._queue: asyncio.Queue[UtteranceClosed | object] = asyncio.Queue(
            maxsize=maxsize,
        )
        self._task: asyncio.Task[None] | None = None

    @property
    def call_sid(self) -> str | None:
        return self._call_sid

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run(),
            name=f"voice-stream-utterance-worker-{self._call_sid or '?'}",
        )

    def enqueue(self, result: UtteranceClosed) -> None:
        if self._control.call_ended:
            logger.info(
                "Voice stream utterance #%s not enqueued — call ended callSid=%s",
                result.index,
                self._call_sid or "?",
            )
            return
        logger.info(
            "Voice stream utterance closed #%s duration_ms=%s bytes=%s callSid=%s",
            result.index,
            result.duration_ms,
            len(result.pcm16_16k),
            self._call_sid or "?",
        )
        try:
            self._queue.put_nowait(result)
        except asyncio.QueueFull:
            logger.warning(
                "Voice stream utterance queue full (max=%s) — dropping #%s callSid=%s",
                self._queue.maxsize,
                result.index,
                self._call_sid or "?",
            )

    async def shutdown(self) -> None:
        """Stop after draining queued utterances (or cancel if call already ended)."""
        if self._task is None:
            return
        if self._task.done():
            self._task = None
            return
        if self._control.call_ended:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            return
        await self._queue.put(_STREAM_QUEUE_SENTINEL)
        try:
            await self._task
        finally:
            self._task = None

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is _STREAM_QUEUE_SENTINEL:
                    return
                if self._control.call_ended:
                    continue
                await _process_utterance_turn(
                    item,
                    call_sid=self._call_sid,
                    stream_sid=self._stream_sid,
                    websocket=self._websocket,
                    control=self._control,
                )
            finally:
                self._queue.task_done()
            if self._control.call_ended:
                return


def _register_mark_event(control: StreamCallControl, name: str) -> asyncio.Event:
    event = asyncio.Event()
    control.mark_events[name] = event
    return event


def _notify_mark_received(control: StreamCallControl, name: str) -> None:
    event = control.mark_events.get(name)
    if event is not None and not event.is_set():
        event.set()


async def _wait_for_stream_mark(
    control: StreamCallControl,
    name: str,
    *,
    timeout_sec: float,
) -> bool:
    """Wait until Twilio echoes ``name`` or timeout. Returns True if mark received."""
    event = control.mark_events.get(name)
    if event is None:
        return False
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_sec)
        return True
    except asyncio.TimeoutError:
        return False


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
) -> tuple[str, bool]:
    """
    Same agent path as record mode (``process_voice_inbound_turn`` → ``run_voice_agent_turn``).

    Uses a **fresh** ``voice_turn_out`` per call (never shared across utterances).
    Returns ``(response_text, should_hangup)`` — same semantics as record
    (``bool(voice_turn_out.get("should_hangup"))`` after ``attend_inbound_message``).
    """
    from app.core.database import AsyncSessionLocal
    from app.services.voice_turn_processor import run_voice_agent_turn

    voice_turn_out: dict[str, object] = {}
    async with AsyncSessionLocal() as session:
        response_text = await run_voice_agent_turn(
            session,
            from_number=from_number,
            transcript=transcript,
            call_sid=call_sid,
            voice_turn_out=voice_turn_out,
        )
    return (response_text or "").strip(), bool(voice_turn_out.get("should_hangup"))


async def _finalize_stream_farewell_call(
    *,
    call_sid: str,
    from_number: str,
) -> None:
    """Tabulação + LI terminal (espelha record turn-ready com ``should_hangup``)."""
    from app.core.database import AsyncSessionLocal
    from app.services.voice_call_finalize import (
        VOICE_FAREWELL_ORIGEM,
        finalize_voice_call_terminal,
    )
    from app.services.voice_call_state import clear_voice_call_state

    async with AsyncSessionLocal() as session:
        await finalize_voice_call_terminal(
            session,
            call_sid=call_sid,
            from_number=from_number or None,
            origem=VOICE_FAREWELL_ORIGEM,
        )
        await session.commit()
    clear_voice_call_state(call_sid)


async def _execute_agent_farewell_hangup(
    *,
    call_sid: str,
    from_number: str,
    stream_sid: str,
    websocket: WebSocket,
    control: StreamCallControl,
) -> None:
    """Audio already sent — mark → await playback → REST end call."""
    waiting_mark = FAREWELL_DONE_MARK
    _register_mark_event(control, waiting_mark)
    await _send_mark(websocket, stream_sid=stream_sid, name=waiting_mark)

    timeout_sec = float(settings.voice_stream_farewell_mark_timeout_seconds)
    mark_received = await _wait_for_stream_mark(
        control,
        waiting_mark,
        timeout_sec=timeout_sec,
    )
    if not mark_received:
        logger.warning(
            "Voice stream farewell mark timeout callSid=%s mark=%s timeout_sec=%s",
            call_sid,
            waiting_mark,
            timeout_sec,
        )

    end_started = time.perf_counter()
    await end_twilio_call(call_sid)
    end_call_ms = (time.perf_counter() - end_started) * 1000

    try:
        await _finalize_stream_farewell_call(
            call_sid=call_sid,
            from_number=from_number,
        )
    except Exception as exc:
        logger.error(
            "Voice stream farewell finalize failed callSid=%s: %s",
            call_sid,
            exc,
            exc_info=True,
        )

    control.call_ended = True
    logger.info(
        "Voice stream hangup callSid=%s reason=agent_farewell waiting_mark=%s "
        "mark_received=%s end_call_ms=%s",
        call_sid,
        waiting_mark,
        mark_received,
        f"{end_call_ms:.0f}",
    )


async def _synthesize_stream_mulaw_frames(response_text: str) -> StreamTtsResult:
    """Coqui @ 8 kHz WAV (phrase-aware, batch) → PCM16 → μ-law frames."""
    wav_bytes = await synthesize_voice_stream_wav(
        response_text,
        sample_rate=STREAM_TTS_SAMPLE_RATE,
    )
    pcm16 = wav_bytes_to_pcm16_mono(
        wav_bytes,
        expected_rate=STREAM_TTS_SAMPLE_RATE,
    )
    mulaw = pcm16_to_mulaw(pcm16)
    return StreamTtsResult(
        wav_bytes=wav_bytes,
        mulaw=mulaw,
        frames=chunk_mulaw(mulaw),
    )


async def _stream_response_tts_to_ws(
    response_text: str,
    *,
    websocket: WebSocket,
    stream_sid: str,
    control: StreamCallControl,
    barge_on: bool,
    capture_on: bool,
    stt_end_at: float | None = None,
) -> StreamTtsPlaybackResult:
    """Phrase-streamed TTS: synthesize and send frames concurrently (FIFO)."""
    ttfa_from_stt_ms: float | None = None
    first_frame_sent = False

    async def on_frame(frame: bytes) -> bool:
        nonlocal ttfa_from_stt_ms, first_frame_sent
        if len(frame) != MULAW_FRAME_BYTES:
            logger.error(
                "Voice stream agent frame invalid size=%s (expected %s)",
                len(frame),
                MULAW_FRAME_BYTES,
            )
            frame = frame + bytes([MULAW_SILENCE_BYTE]) * (
                MULAW_FRAME_BYTES - len(frame)
            )
        if barge_on and control.playback_interrupt.is_set():
            return False
        outbound: dict[str, Any] = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(frame).decode("ascii")},
        }
        await websocket.send_text(json.dumps(outbound))
        if (
            capture_on
            and control.echo_capture is not None
            and control.echo_capture.segment_active
        ):
            control.echo_capture.record_outbound(frame, ts=time.perf_counter())
        if not first_frame_sent:
            first_frame_sent = True
            if stt_end_at is not None:
                ttfa_from_stt_ms = (time.perf_counter() - stt_end_at) * 1000
        return True

    playback = await stream_phrase_tts_playback(
        response_text,
        sample_rate=STREAM_TTS_SAMPLE_RATE,
        on_frame=on_frame,
    )
    if ttfa_from_stt_ms is not None:
        playback.ttfa_ms = ttfa_from_stt_ms
    return playback


async def _process_utterance_turn(
    result: UtteranceClosed,
    *,
    call_sid: str | None,
    stream_sid: str | None,
    websocket: WebSocket,
    control: StreamCallControl,
) -> None:
    """
    Fase C+D1+D2a: STT → agent → TTS → μ-law outbound; farewell → mark → REST hangup.

    Invoked serially by ``StreamUtteranceWorker`` (FIFO per call).
    """
    if control.call_ended:
        logger.info(
            "Voice stream utterance #%s skipped — call already ended callSid=%s",
            result.index,
            call_sid or "?",
        )
        return
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
    stt_end_at = time.perf_counter()
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

    if control.call_ended:
        return

    agent_started = time.perf_counter()
    response_text = ""
    should_hangup = False
    try:
        response_text, should_hangup = await _run_voice_agent_for_stream(
            from_number=from_number,
            transcript=transcript,
            call_sid=sid or None,
        )
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
        should_hangup = False

    agent_ms = (time.perf_counter() - agent_started) * 1000
    if not response_text:
        response_text = VOICE_STREAM_AGENT_FALLBACK

    tts_started = time.perf_counter()
    barge_on = bool(settings.voice_stream_barge_in_enabled)
    capture_on = bool(
        settings.voice_stream_echo_debug_capture and control.echo_capture is not None
    )
    if barge_on:
        control.playback_interrupt.clear()

    if barge_on and control.playback_interrupt.is_set():
        logger.info(
            "Voice stream TTS discarded — playback interrupted utterance #%s callSid=%s",
            result.index,
            sid,
        )
        control.end_agent_playback()
        control.playback_interrupt.clear()
        return

    playback: StreamTtsPlaybackResult | None = None
    try:
        if capture_on:
            control.echo_capture.begin_segment(
                call_sid=sid,
                label=f"utterance_{result.index}",
            )
        control.begin_agent_playback()
        playback = await _stream_response_tts_to_ws(
            response_text,
            websocket=websocket,
            stream_sid=stream_sid,
            control=control,
            barge_on=barge_on,
            capture_on=capture_on,
            stt_end_at=stt_end_at,
        )
    except Exception as exc:
        tts_ms = (time.perf_counter() - tts_started) * 1000
        control.end_agent_playback()
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
    frames = playback.frames
    completed = playback.completed

    try:
        schedule_voice_stream_debug_capture(
            call_sid=sid,
            utterance_index=result.index,
            transcript=transcript,
            response_text=response_text,
            coqui_wav_bytes=playback.wav_bytes,
            mulaw_frames=frames,
            extra={
                "agent_ms": round(agent_ms, 1),
                "tts_ms": round(tts_ms, 1),
                "ttfa_ms": round(playback.ttfa_ms, 1) if playback.ttfa_ms else None,
                "phrase_count": playback.phrase_count,
                "stream_sid": stream_sid,
            },
        )
    except Exception as exc:
        logger.warning(
            "Voice stream debug capture schedule failed utterance #%s callSid=%s (ignored): %s",
            result.index,
            sid,
            exc,
        )

    if barge_on and (not completed or control.playback_interrupt.is_set()):
        if capture_on and control.echo_capture is not None:
            control.echo_capture.finalize_segment(reason="barge_in_interrupt")
        logger.info(
            "Voice stream response interrupted utterance #%s callSid=%s "
            "agent_ms=%s tts_ms=%s ttfa_ms=%s response=%r",
            result.index,
            sid,
            agent_ms,
            tts_ms,
            playback.ttfa_ms,
            response_text,
        )
        control.end_agent_playback()
        control.playback_interrupt.clear()
        return

    try:
        if should_hangup:
            await _execute_agent_farewell_hangup(
                call_sid=sid,
                from_number=from_number,
                stream_sid=stream_sid,
                websocket=websocket,
                control=control,
            )
        else:
            await _send_mark(
                websocket,
                stream_sid=stream_sid,
                name=AGENT_RESPONSE_MARK,
            )
    except Exception as exc:
        control.end_agent_playback()
        logger.error(
            "Voice stream outbound audio failed utterance #%s callSid=%s: %s",
            result.index,
            sid,
            exc,
        )
        return

    logger.info(
        "Voice stream agent response callSid=%s utterance#%s agent_ms=%s tts_ms=%s "
        "ttfa_ms=%s phrases=%s audio_frames=%s hangup=%s response=%r",
        sid,
        result.index,
        agent_ms,
        tts_ms,
        playback.ttfa_ms,
        playback.phrase_count,
        len(frames),
        should_hangup,
        response_text,
    )


async def _finalize_session(
    session: VoiceStreamSession | None,
    *,
    utterance_worker: StreamUtteranceWorker | None,
    control: StreamCallControl | None = None,
) -> None:
    if control is not None and control.echo_capture is not None:
        control.echo_capture.finalize_call()
    if session is not None:
        flushed = session.flush()
        if flushed is not None and utterance_worker is not None:
            logger.info(
                "Voice stream utterance flushed on teardown #%s duration_ms=%s callSid=%s",
                flushed.index,
                flushed.duration_ms,
                utterance_worker.call_sid or "?",
            )
            utterance_worker.enqueue(flushed)

    if utterance_worker is not None:
        await utterance_worker.shutdown()


async def _send_mulaw_frames(
    websocket: WebSocket,
    *,
    stream_sid: str,
    frames: list[bytes],
    label: str,
    control: StreamCallControl | None = None,
    barge_in_enabled: bool = False,
) -> bool:
    """
    Send outbound μ-law frames to Twilio (base64 in JSON media events).

    Returns True if all frames were sent, False if aborted via barge-in interrupt.
    Interrupt checks apply only when ``barge_in_enabled`` (D1 parity when off).
    """
    for index, frame in enumerate(frames, start=1):
        if len(frame) != MULAW_FRAME_BYTES:
            logger.error(
                "Voice stream %s frame %s/%s invalid size=%s (expected %s)",
                label,
                index,
                len(frames),
                len(frame),
                MULAW_FRAME_BYTES,
            )
            frame = frame + bytes([MULAW_SILENCE_BYTE]) * (MULAW_FRAME_BYTES - len(frame))
        if (
            barge_in_enabled
            and control is not None
            and control.playback_interrupt.is_set()
        ):
            logger.info(
                "Voice stream %s aborted at frame %s/%s",
                label,
                index,
                len(frames),
            )
            return False
        outbound: dict[str, Any] = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(frame).decode("ascii")},
        }
        await websocket.send_text(json.dumps(outbound))
        if (
            control is not None
            and control.echo_capture is not None
            and control.echo_capture.segment_active
            and label == "agent"
        ):
            control.echo_capture.record_outbound(frame, ts=time.perf_counter())
        if index == 1 or index == len(frames) or index % 10 == 0:
            logger.info(
                "Voice stream %s: frame %s/%s (%s bytes μ-law)",
                label,
                index,
                len(frames),
                len(frame),
            )
    return True


async def _send_clear(websocket: WebSocket, *, stream_sid: str) -> None:
    """Twilio ``clear`` — empties buffered outbound audio (barge-in)."""
    payload = {
        "event": "clear",
        "streamSid": stream_sid,
    }
    await websocket.send_text(json.dumps(payload))
    logger.info("Voice stream clear sent streamSid=%s", stream_sid)


async def _send_mark(websocket: WebSocket, *, stream_sid: str, name: str) -> None:
    """Optional mark — Twilio echoes it when playback catches up."""
    payload = {
        "event": "mark",
        "streamSid": stream_sid,
        "mark": {"name": name},
    }
    await websocket.send_text(json.dumps(payload))
    logger.info("Voice stream mark sent name=%s streamSid=%s", name, stream_sid)


async def _handle_barge_in(
    websocket: WebSocket,
    *,
    stream_sid: str,
    control: StreamCallControl,
    session: VoiceStreamSession,
    call_sid: str | None,
) -> None:
    """F1 barge-in: clear Twilio buffer + abort worker playback."""
    if not control.request_playback_interrupt():
        return
    logger.info(
        "Voice stream barge-in detected callSid=%s streamSid=%s",
        call_sid or "?",
        stream_sid,
    )
    await _send_clear(websocket, stream_sid=stream_sid)
    control.end_agent_playback()
    session.reset_barge_in_detection()


async def handle_voice_media_stream(websocket: WebSocket) -> None:
    """
    Handle bidirectional Twilio Media Stream.

    Fase A: log + intro beep + optional echo.
    Fase B: inbound μ-law → VAD utterance detection.
    Fase C: utterance → FIFO worker (STT → agent → TTS, serial per call).
    Fase D1: STT → agent → TTS 8 kHz → μ-law outbound (FIFO worker per call).
    Fase D2a: farewell → mark → REST hangup.
    Fase F1: barge-in (clear + abort playback on sustained lead speech).
    """
    await websocket.accept()
    logger.info("Voice Media Stream WebSocket accepted")

    stream_sid: str | None = None
    call_sid: str | None = None
    session: VoiceStreamSession | None = None
    utterance_worker: StreamUtteranceWorker | None = None
    echo_enabled = bool(settings.voice_stream_echo_debug)
    media_in_count = 0
    media_out_count = 0
    control = StreamCallControl()
    if settings.voice_stream_echo_debug_capture:
        control.echo_capture = PlaybackEchoCapture()
        logger.info(
            "Voice stream echo debug capture enabled callSid=%s (barge_in=%s)",
            "pending",
            settings.voice_stream_barge_in_enabled,
        )

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

                session.agent_speaking_check = lambda: control.agent_speaking

                utterance_worker = StreamUtteranceWorker(
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                    websocket=websocket,
                    control=control,
                )
                utterance_worker.start()

                if control.echo_capture is not None:
                    control.echo_capture.call_sid = call_sid

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
                    if control.call_ended:
                        continue
                    try:
                        frame_mulaw = base64.b64decode(payload_b64)
                    except Exception:
                        logger.warning(
                            "Voice stream invalid media payload callSid=%s",
                            call_sid or "?",
                        )
                        frame_mulaw = b""
                    if frame_mulaw:
                        if (
                            control.echo_capture is not None
                            and control.echo_capture.segment_active
                        ):
                            control.echo_capture.record_inbound(
                                frame_mulaw,
                                ts=time.perf_counter(),
                            )
                        feed_result = session.feed_mulaw_frame(frame_mulaw)
                        if (
                            feed_result.barge_in
                            and stream_sid
                            and settings.voice_stream_barge_in_enabled
                        ):
                            await _handle_barge_in(
                                websocket,
                                stream_sid=stream_sid,
                                control=control,
                                session=session,
                                call_sid=call_sid,
                            )
                        if (
                            feed_result.utterance is not None
                            and utterance_worker is not None
                        ):
                            utterance_worker.enqueue(feed_result.utterance)

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
                _notify_mark_received(control, str(mark_name))
                if mark_name == "intro_done" and session is not None and not session.listening:
                    session.listening = True
                    logger.info(
                        "Voice stream listening enabled (intro_done mark) callSid=%s",
                        call_sid or "?",
                    )
                if mark_name in (AGENT_RESPONSE_MARK, FAREWELL_DONE_MARK):
                    if control.echo_capture is not None:
                        control.echo_capture.finalize_segment(
                            reason=f"mark_{mark_name}",
                        )
                    control.end_agent_playback()
                    control.playback_interrupt.clear()
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
                    utterance_worker=utterance_worker,
                    control=control,
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
            utterance_worker=utterance_worker,
            control=control,
        )
    except Exception:
        logger.exception(
            "Voice stream handler error callSid=%s streamSid=%s",
            call_sid or "?",
            stream_sid or "?",
        )
        await _finalize_session(
            session,
            utterance_worker=utterance_worker,
            control=control,
        )
        raise
