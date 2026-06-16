"""Processamento pesado de turno de voz inbound (STT → agente → TTS)."""

from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from agents.channels.voice.tts_stt import speech_to_text
from agents.channels.voice.twilio_voice_client import download_recording
from app.services.inbound_attendance import attend_inbound_message
from app.services.settings_sync import ensure_settings_fresh_async
from app.services.voice_audio import gerar_audio_chamada
from app.services.voice_call_state import reset_silence_stage
from app.services.voice_turn_state import (
    mark_turn_error,
    mark_turn_ready,
    mark_turn_silence_stt,
)
from worker.tasks.conversation_routing import resolve_inbound_agent
from worker.tasks.lead_tracking import find_lead_by_channel_user

logger = logging.getLogger(__name__)

VOICE_MIN_RECORDING_DURATION_SEC = 1.0


def _is_stt_silence(recording_url: str, duration: float, transcript: str) -> bool:
    if not (recording_url or "").strip():
        return True
    if duration < VOICE_MIN_RECORDING_DURATION_SEC:
        return True
    if not (transcript or "").strip():
        return True
    return False


async def run_voice_agent_turn(
    session: AsyncSession,
    *,
    from_number: str,
    transcript: str,
    call_sid: str | None = None,
    agent_timings: dict[str, float] | None = None,
) -> str:
    """Roteamento receptivo + grafo (sem Celery). Retorna texto da resposta."""
    await ensure_settings_fresh_async()

    user_id = (from_number or "").strip()
    if not user_id:
        raise ValueError("From vazio no callback de gravação")

    lead = await find_lead_by_channel_user(session, "voice", user_id)
    agent = await resolve_inbound_agent(session, lead, "voice", force_receptive=True)

    logger.info(
        "Voice record turn user_id=%s lead=%s agent=%s (%s)",
        user_id,
        lead.id if lead else None,
        agent.name,
        agent.mode.value,
    )

    response_text = await attend_inbound_message(
        session,
        channel="voice",
        user_id=user_id,
        message=transcript,
        agent=agent,
        lead=lead,
        bind_capacity=False,
        twilio_call_sid=call_sid,
        agent_timings_out=agent_timings,
    )
    await session.commit()
    return (response_text or "").strip()


async def process_voice_inbound_turn(
    *,
    call_sid: str,
    turn_id: str,
    recording_url: str,
    from_number: str,
    recording_duration: float = 0.0,
) -> None:
    """
    Pipeline completo do turno (worker Celery).

    Atualiza Redis voice_turn:{call_sid}:{turn_id} para ready, silence_stt ou error.
    """
    started = time.perf_counter()
    timings: dict[str, float] = {}
    sid = (call_sid or "").strip()
    tid = (turn_id or "").strip()

    try:
        t0 = time.perf_counter()
        audio_bytes = await download_recording(recording_url)
        timings["download_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        transcript = (
            await speech_to_text(
                audio_bytes,
                language="pt",
                filename="audio.wav",
                content_type="audio/wav",
            )
        ).strip()
        timings["stt_ms"] = (time.perf_counter() - t0) * 1000

        if _is_stt_silence(recording_url, recording_duration, transcript):
            mark_turn_silence_stt(sid, tid)
            timings["total_ms"] = (time.perf_counter() - started) * 1000
            logger.info(
                "Voice turn silence_stt call_sid=%s turn_id=%s timings=%s",
                sid,
                tid,
                _format_timings(timings),
            )
            return

        if sid:
            reset_silence_stage(sid, from_number=from_number)

        from app.core.database import AsyncSessionLocal

        t0 = time.perf_counter()
        agent_timings: dict[str, float] = {}
        async with AsyncSessionLocal() as session:
            response_text = await run_voice_agent_turn(
                session,
                from_number=from_number,
                transcript=transcript,
                call_sid=sid or None,
                agent_timings=agent_timings,
            )
        timings["agent_ms"] = (time.perf_counter() - t0) * 1000
        timings.update(agent_timings)

        cleaned = (response_text or "").strip()
        if not cleaned:
            cleaned = "Desculpe, não consegui formular uma resposta."

        t0 = time.perf_counter()
        filename = await gerar_audio_chamada(cleaned)
        timings["tts_ms"] = (time.perf_counter() - t0) * 1000

        mark_turn_ready(sid, tid, audio_filename=filename)
        timings["total_ms"] = (time.perf_counter() - started) * 1000
        response_chars = len(cleaned)
        logger.info(
            "Voice turn processed call_sid=%s turn_id=%s audio=%s "
            "transcript_len=%s response_chars=%s timings=%s",
            sid,
            tid,
            filename,
            len(transcript),
            response_chars,
            _format_timings(timings),
        )
    except Exception as exc:
        timings["total_ms"] = (time.perf_counter() - started) * 1000
        logger.exception(
            "Voice turn failed call_sid=%s turn_id=%s timings=%s",
            sid,
            tid,
            _format_timings(timings),
        )
        mark_turn_error(sid, tid, error=str(exc))


def _format_timings(timings: dict[str, float]) -> str:
    parts = []
    for key in (
        "download_ms",
        "stt_ms",
        "intent_ms",
        "rag_ms",
        "response_ms",
        "agent_ms",
        "tts_ms",
        "total_ms",
    ):
        if key in timings:
            parts.append(f"{key}={timings[key]:.0f}")
    return " ".join(parts)
