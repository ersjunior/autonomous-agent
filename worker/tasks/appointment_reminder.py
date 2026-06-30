"""Task dedicada — entrega de lembrete de agendamento (isenta do gate de campanha)."""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.appointment_reminder_text import build_due_message, build_reminder_message
from app.core.config import WhatsAppTemplatePurpose
from app.core.database import AsyncSessionLocal
from app.models.appointment import Appointment
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.services.appointment_reminder_service import resolve_campaign_for_lead
from app.services.outbound_delivery import deliver_outbound_message
from app.services.whatsapp_outbound import (
    build_appointment_content_variables,
    resolve_whatsapp_send_mode,
)
from worker.async_runner import run_celery_async
from worker.celery_app import celery
from worker.tasks.lead_tracking import upsert_lead_interaction
from worker.tasks.outbound_campaign import _fetch_lead_interaction, _resolve_recipient

logger = logging.getLogger(__name__)

ReminderKind = Literal["reminder", "due"]

_SUPPORTED_CHANNELS = frozenset({"voice", "telegram", "whatsapp"})


def _appointment_template_purpose(kind: ReminderKind) -> WhatsAppTemplatePurpose:
    return "appointment_reminder" if kind == "reminder" else "appointment_due"


async def _record_reminder_interaction(
    session,
    *,
    lead: Lead,
    campaign_id: uuid.UUID,
    channel: str,
    kind: ReminderKind,
    appointment_id: uuid.UUID,
    delivery,
) -> None:
    """Registra tentativa outbound quando há campanha resolvível (opcional)."""
    devolutiva = f"appointment_{kind}:{appointment_id}"[:500]
    kwargs: dict = {
        "touch_agent_message": True,
        "record_outbound_attempt": True,
        "devolutiva": devolutiva,
    }
    if channel == "voice" and delivery.twilio_call_sid:
        kwargs["twilio_call_sid"] = delivery.twilio_call_sid
        kwargs["status"] = "acionado"
    elif channel == "whatsapp" and delivery.twilio_message_sid:
        kwargs["twilio_message_sid"] = delivery.twilio_message_sid
        kwargs["last_delivery_status"] = delivery.initial_delivery_status
        kwargs["status"] = "acionado"
    elif channel == "telegram":
        kwargs["status"] = "acionado"
    await upsert_lead_interaction(
        session,
        lead.id,
        campaign_id,
        channel,
        **kwargs,
    )


async def _send_appointment_reminder_with_session(
    session,
    appointment_id: str,
    kind: ReminderKind,
    *,
    commit: bool = True,
) -> dict:
    """
    Entrega lembrete/acionamento na hora.

    Lembrete de agendamento = contato consentido; não passa pelo gate de modo de campanha.
    """
    result = await session.execute(
        select(Appointment)
        .options(
            selectinload(Appointment.lead).selectinload(Lead.lead_base),
        )
        .where(Appointment.id == uuid.UUID(appointment_id))
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        raise ValueError(f"Appointment {appointment_id} not found")

    lead = appointment.lead
    if lead is None:
        return {"ok": False, "reason": "lead_not_found"}

    channel = (appointment.channel or "").lower()
    if channel not in _SUPPORTED_CHANNELS:
        return {"ok": False, "reason": "unsupported_channel", "channel": channel}

    recipient = _resolve_recipient(lead, channel)
    if not recipient:
        return {"ok": False, "reason": "no_recipient", "channel": channel}

    text = (
        build_reminder_message(appointment.starts_at)
        if kind == "reminder"
        else build_due_message(appointment.starts_at)
    )

    content_sid: str | None = None
    content_variables: dict[str, str] | None = None
    whatsapp_mode: str | None = None
    campaign = await resolve_campaign_for_lead(session, lead)

    if channel == "whatsapp":
        record = None
        if campaign is not None:
            record = await _fetch_lead_interaction(
                session,
                lead.id,
                campaign.id,
                channel,
            )
        purpose = _appointment_template_purpose(kind)
        send_mode = resolve_whatsapp_send_mode(purpose, record, lead=lead)
        whatsapp_mode = send_mode.mode
        if send_mode.mode == "template":
            content_sid = send_mode.content_sid
            content_variables = build_appointment_content_variables(
                lead,
                appointment.starts_at,
            )
            text = ""

    delivery = await deliver_outbound_message(
        channel,
        recipient,
        text,
        lead=lead,
        content_sid=content_sid,
        content_variables=content_variables,
    )
    if not delivery.ok:
        return {
            "ok": False,
            "reason": "delivery_failed",
            "channel": channel,
            "error": delivery.error,
        }

    recorded = False
    if campaign is not None:
        await _record_reminder_interaction(
            session,
            lead=lead,
            campaign_id=campaign.id,
            channel=channel,
            kind=kind,
            appointment_id=appointment.id,
            delivery=delivery,
        )
        recorded = True

    if commit:
        await session.commit()

    result_payload: dict = {
        "ok": True,
        "appointment_id": appointment_id,
        "kind": kind,
        "channel": channel,
        "lead_interaction_recorded": recorded,
    }
    if whatsapp_mode is not None:
        result_payload["whatsapp_mode"] = whatsapp_mode
        if content_sid:
            result_payload["content_sid"] = content_sid
    return result_payload


async def _send_appointment_reminder_async(
    appointment_id: str,
    kind: ReminderKind,
) -> dict:
    async with AsyncSessionLocal() as session:
        return await _send_appointment_reminder_with_session(
            session, appointment_id, kind, commit=True
        )


@celery.task(name="worker.tasks.appointment_reminder.send_appointment_reminder")
def send_appointment_reminder(appointment_id: str, kind: str) -> dict:
    """Celery: entrega direta de lembrete de agendamento (voice/telegram/whatsapp)."""
    if kind not in ("reminder", "due"):
        raise ValueError(f"Invalid reminder kind: {kind}")
    return run_celery_async(_send_appointment_reminder_async(appointment_id, kind))
