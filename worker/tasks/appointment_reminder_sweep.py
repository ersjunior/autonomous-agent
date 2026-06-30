"""
Sweep de lembretes proativos de agendamento (voz + telegram — Fatia 1).

Dois disparos por appointment:
  - Lembrete antecipado → reminder_sent_at
  - Acionamento na hora → due_notified_at

WhatsApp e channel NULL são ignorados nesta fatia (skipped_whatsapp).

Entrega via send_appointment_reminder (caminho direto, isento do gate RECEPTIVE de campanhas).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.appointment_reminder_text import build_due_message, build_reminder_message
from app.core.database import AsyncSessionLocal
from app.services.appointment_reminder_service import plan_appointment_reminder_sweep
from worker.async_runner import run_celery_async
from worker.celery_app import celery
from worker.tasks.appointment_reminder import send_appointment_reminder
from worker.tasks.outbound_campaign import _resolve_recipient

logger = logging.getLogger(__name__)


def _empty_stats() -> dict[str, int]:
    return {
        "reminders_sent": 0,
        "due_notified": 0,
        "skipped_whatsapp": 0,
        "skipped_no_recipient": 0,
    }


async def _try_dispatch(
    session,
    appointment,
    *,
    kind: str,
    mark_attr: str,
    now: datetime,
    stats: dict[str, int],
    counter_key: str,
) -> bool:
    """
    Valida destinatário, marca idempotência e enfileira entrega direta do lembrete.

    Lembrete de agendamento = contato consentido; não passa pelo gate de modo de campanha.
    """
    lead = appointment.lead
    if lead is None:
        stats["skipped_no_recipient"] += 1
        return False

    channel = (appointment.channel or "").lower()
    if not channel:
        stats["skipped_whatsapp"] += 1
        return False

    if channel not in ("voice", "telegram"):
        stats["skipped_whatsapp"] += 1
        return False

    recipient = _resolve_recipient(lead, channel)
    if not recipient:
        stats["skipped_no_recipient"] += 1
        logger.warning(
            "Appointment reminder: sem destinatário appointment=%s lead=%s channel=%s",
            appointment.id,
            lead.id,
            channel,
        )
        return False

    setattr(appointment, mark_attr, now)
    send_appointment_reminder.delay(str(appointment.id), kind)
    stats[counter_key] += 1
    logger.info(
        "Appointment reminder enqueued kind=%s %s appointment=%s lead=%s channel=%s",
        kind,
        mark_attr,
        appointment.id,
        lead.id,
        channel,
    )
    return True


async def _sweep_appointment_reminders_with_session(session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    stats = _empty_stats()
    plan = await plan_appointment_reminder_sweep(session, now)
    stats["skipped_whatsapp"] = plan.skipped_whatsapp

    changed = False

    for appointment in plan.reminders:
        if await _try_dispatch(
            session,
            appointment,
            kind="reminder",
            mark_attr="reminder_sent_at",
            now=now,
            stats=stats,
            counter_key="reminders_sent",
        ):
            changed = True

    for appointment in plan.due:
        if await _try_dispatch(
            session,
            appointment,
            kind="due",
            mark_attr="due_notified_at",
            now=now,
            stats=stats,
            counter_key="due_notified",
        ):
            changed = True

    if changed:
        await session.commit()

    if any(stats[k] for k in ("reminders_sent", "due_notified", "skipped_whatsapp")):
        logger.info("Appointment reminder sweep: %s", stats)

    return stats


async def _sweep_appointment_reminders_async() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        return await _sweep_appointment_reminders_with_session(session)


@celery.task(name="worker.tasks.appointment_reminder_sweep.sweep_appointment_reminders")
def sweep_appointment_reminders() -> dict[str, int]:
    """Beat: lembrete antecipado e acionamento na hora (voice/telegram)."""
    return run_celery_async(_sweep_appointment_reminders_async())
