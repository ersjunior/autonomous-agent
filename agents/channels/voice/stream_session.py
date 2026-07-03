"""Twilio Media Streams WebSocket session handler (transport-only, Fase A)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from agents.channels.voice.mulaw_codec import INTRO_FRAMES, MULAW_FRAME_BYTES
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
    Handle bidirectional Twilio Media Stream (Fase A: log + intro beep + optional echo).

    Protocol: connected → start → media* → mark* → stop
    """
    await websocket.accept()
    logger.info("Voice Media Stream WebSocket accepted")

    stream_sid: str | None = None
    call_sid: str | None = None
    echo_enabled = bool(settings.voice_stream_echo_debug)
    media_in_count = 0
    media_out_count = 0

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
                continue

            if event == "media":
                media_in_count += 1
                media_block = message.get("media") or {}
                payload_b64 = (media_block.get("payload") or "").strip()
                track = media_block.get("track", "?")
                if media_in_count <= 3 or media_in_count % MEDIA_LOG_EVERY_N == 0:
                    logger.info(
                        "Voice stream media IN #%s track=%s payload_len=%s callSid=%s",
                        media_in_count,
                        track,
                        len(payload_b64),
                        call_sid or "?",
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
                continue

            if event == "stop":
                logger.info(
                    "Voice stream stop streamSid=%s callSid=%s media_in=%s media_out_echo=%s",
                    sid_in_msg or stream_sid,
                    call_sid or "?",
                    media_in_count,
                    media_out_count,
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
    except Exception:
        logger.exception(
            "Voice stream handler error callSid=%s streamSid=%s",
            call_sid or "?",
            stream_sid or "?",
        )
        raise
