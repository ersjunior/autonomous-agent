"""Detecção de appointments elegíveis para lembrete antecipado e acionamento na hora."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.appointment import Appointment, AppointmentStatus
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase

ACTIVE_REMINDER_STATUSES = (
    AppointmentStatus.SCHEDULED.value,
    AppointmentStatus.CONFIRMED.value,
)

SWEEP_CHANNELS = ("voice", "telegram", "whatsapp")


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reminder_window_bounds(
    starts_at: datetime,
    *,
    lead_minutes: int | None = None,
    grace_minutes: int | None = None,
) -> tuple[datetime, datetime]:
    """Janela [starts - lead, starts - grace] em UTC."""
    start = _aware(starts_at)
    lead = lead_minutes if lead_minutes is not None else settings.appointment_reminder_lead_minutes
    grace = grace_minutes if grace_minutes is not None else settings.appointment_reminder_grace_minutes
    return start - timedelta(minutes=lead), start - timedelta(minutes=grace)


def is_in_reminder_window(
    starts_at: datetime,
    now: datetime,
    *,
    lead_minutes: int | None = None,
    grace_minutes: int | None = None,
) -> bool:
    """True se now está em [starts - lead, starts - grace]."""
    window_start, window_end = reminder_window_bounds(
        starts_at,
        lead_minutes=lead_minutes,
        grace_minutes=grace_minutes,
    )
    current = _aware(now)
    return window_start <= current <= window_end


def is_in_due_window(
    starts_at: datetime,
    now: datetime,
    *,
    tolerance_minutes: int | None = None,
) -> bool:
    """True se now está em [starts, starts + tolerance]."""
    start = _aware(starts_at)
    current = _aware(now)
    tolerance = (
        tolerance_minutes
        if tolerance_minutes is not None
        else settings.appointment_due_tolerance_minutes
    )
    return start <= current <= start + timedelta(minutes=tolerance)


def _reminder_starts_at_bounds(now: datetime) -> tuple[datetime, datetime]:
    """
    Inverte a janela de lembrete para filtro SQL:
    now + grace <= starts_at <= now + lead.
    """
    current = _aware(now)
    grace = settings.appointment_reminder_grace_minutes
    lead = settings.appointment_reminder_lead_minutes
    return current + timedelta(minutes=grace), current + timedelta(minutes=lead)


def _due_starts_at_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Inverte janela na hora: now - tolerance <= starts_at <= now."""
    current = _aware(now)
    tolerance = settings.appointment_due_tolerance_minutes
    return current - timedelta(minutes=tolerance), current


def _appointment_load_options():
    return (
        selectinload(Appointment.lead)
        .selectinload(Lead.lead_base)
        .selectinload(LeadBase.lead_base_channels),
    )


def _base_status_filter():
    return Appointment.status.in_(ACTIVE_REMINDER_STATUSES)


def _channel_in_sweep():
    return Appointment.channel.in_(SWEEP_CHANNELS)


def _channel_skipped_no_channel():
    return Appointment.channel.is_(None)


async def fetch_reminder_candidates(
    session: AsyncSession,
    now: datetime,
) -> list[Appointment]:
    """Appointments voice/telegram na janela de lembrete antecipado, sem reminder_sent_at."""
    starts_min, starts_max = _reminder_starts_at_bounds(now)
    result = await session.execute(
        select(Appointment)
        .options(*_appointment_load_options())
        .where(
            _base_status_filter(),
            Appointment.reminder_sent_at.is_(None),
            _channel_in_sweep(),
            Appointment.starts_at >= starts_min,
            Appointment.starts_at <= starts_max,
        )
        .order_by(Appointment.starts_at.asc())
    )
    return list(result.scalars().all())


async def fetch_due_candidates(
    session: AsyncSession,
    now: datetime,
) -> list[Appointment]:
    """Appointments voice/telegram na janela na hora, sem due_notified_at."""
    starts_min, starts_max = _due_starts_at_bounds(now)
    result = await session.execute(
        select(Appointment)
        .options(*_appointment_load_options())
        .where(
            _base_status_filter(),
            Appointment.due_notified_at.is_(None),
            _channel_in_sweep(),
            Appointment.starts_at >= starts_min,
            Appointment.starts_at <= starts_max,
        )
        .order_by(Appointment.starts_at.asc())
    )
    return list(result.scalars().all())


async def count_skipped_no_channel_in_windows(
    session: AsyncSession,
    now: datetime,
) -> int:
    """Conta appointments sem canal que estariam elegíveis mas não têm destino."""
    rem_min, rem_max = _reminder_starts_at_bounds(now)
    due_min, due_max = _due_starts_at_bounds(now)
    result = await session.execute(
        select(Appointment.id).where(
            _base_status_filter(),
            _channel_skipped_no_channel(),
            or_(
                and_(
                    Appointment.reminder_sent_at.is_(None),
                    Appointment.starts_at >= rem_min,
                    Appointment.starts_at <= rem_max,
                ),
                and_(
                    Appointment.due_notified_at.is_(None),
                    Appointment.starts_at >= due_min,
                    Appointment.starts_at <= due_max,
                ),
            ),
        )
    )
    return len(list(result.scalars().all()))


async def resolve_campaign_for_lead(
    session: AsyncSession,
    lead: Lead,
) -> Campaign | None:
    """Campanha do lead via lead_base.campaign_id."""
    if lead.lead_base is None:
        return None
    result = await session.execute(
        select(Campaign)
        .options(selectinload(Campaign.agent))
        .where(Campaign.id == lead.lead_base.campaign_id)
    )
    return result.scalar_one_or_none()


@dataclass(frozen=True)
class AppointmentReminderSweepPlan:
    reminders: list[Appointment]
    due: list[Appointment]
    skipped_no_channel: int


async def plan_appointment_reminder_sweep(
    session: AsyncSession,
    now: datetime,
) -> AppointmentReminderSweepPlan:
    """Agrega candidatos e contagem de skips sem canal."""
    reminders = await fetch_reminder_candidates(session, now)
    due = await fetch_due_candidates(session, now)
    skipped = await count_skipped_no_channel_in_windows(session, now)
    return AppointmentReminderSweepPlan(
        reminders=reminders,
        due=due,
        skipped_no_channel=skipped,
    )
