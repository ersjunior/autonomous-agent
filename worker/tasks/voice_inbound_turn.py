"""Celery — processamento assíncrono de turno de voz inbound (STT → LLM → TTS)."""

from __future__ import annotations

import logging

from worker.async_runner import run_celery_async
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _process_voice_inbound_turn_async(
    call_sid: str,
    turn_id: str,
    recording_url: str,
    from_number: str,
    recording_duration: float,
) -> None:
    from app.services.voice_turn_processor import process_voice_inbound_turn

    await process_voice_inbound_turn(
        call_sid=call_sid,
        turn_id=turn_id,
        recording_url=recording_url,
        from_number=from_number,
        recording_duration=recording_duration,
    )


@celery.task(bind=True, max_retries=2)
def process_voice_inbound_turn_task(
    self,
    call_sid: str,
    turn_id: str,
    recording_url: str,
    from_number: str,
    recording_duration: float = 0.0,
) -> None:
    """Processa turno de voz fora do webhook Twilio (evita timeout 15s)."""
    try:
        run_celery_async(
            _process_voice_inbound_turn_async(
                call_sid,
                turn_id,
                recording_url,
                from_number,
                float(recording_duration or 0.0),
            )
        )
    except Exception as exc:
        logger.exception(
            "process_voice_inbound_turn_task failed call_sid=%s turn_id=%s",
            call_sid,
            turn_id,
        )
        try:
            from app.services.voice_turn_state import mark_turn_error

            mark_turn_error(call_sid, turn_id, error=str(exc))
        except Exception:
            logger.exception("Failed to mark voice turn error in Redis")
        raise self.retry(exc=exc, countdown=5) from exc
