"""Internal appointment calendar — slot generation, booking and cancellation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activation_window import _parse_hhmm
from app.core.config import (
    APPOINTMENT_DEFAULT_SLOT_MINUTES,
    APPOINTMENT_DEFAULT_WEEKDAYS,
    APPOINTMENT_DEFAULT_WINDOW_END,
    APPOINTMENT_DEFAULT_WINDOW_START,
    APPOINTMENT_TIMEZONE,
    settings,
)
from app.models.appointment import Appointment, AppointmentSource, AppointmentStatus
from app.models.lead import Lead

ACTIVE_BLOCKING_STATUSES = (
    AppointmentStatus.SCHEDULED.value,
    AppointmentStatus.CONFIRMED.value,
)

_WEEKDAY_LABELS_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


class AppointmentError(Exception):
    """Base error for appointment operations."""


class AppointmentNotFoundError(AppointmentError):
    """Appointment id not found for the tenant."""


class AppointmentOwnershipError(AppointmentError):
    """Lead or appointment does not belong to the tenant."""


class AppointmentSlotConflictError(AppointmentError):
    """Requested slot overlaps an existing active appointment."""


@dataclass(frozen=True)
class AvailabilityConfig:
    """Business-hours template for slot generation (Fase D will persist rules)."""

    timezone: str = APPOINTMENT_TIMEZONE
    weekdays: frozenset[int] = APPOINTMENT_DEFAULT_WEEKDAYS
    start: str = APPOINTMENT_DEFAULT_WINDOW_START
    end: str = APPOINTMENT_DEFAULT_WINDOW_END
    slot_minutes: int = APPOINTMENT_DEFAULT_SLOT_MINUTES


def default_availability() -> AvailabilityConfig:
    """Resolved defaults from config (env-overridable slot/window)."""
    return AvailabilityConfig(
        timezone=APPOINTMENT_TIMEZONE,
        weekdays=APPOINTMENT_DEFAULT_WEEKDAYS,
        start=settings.appointment_window_start,
        end=settings.appointment_window_end,
        slot_minutes=settings.appointment_slot_minutes,
    )


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def intervals_overlap(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    a0, a1 = ensure_utc(start_a), ensure_utc(end_a)
    b0, b1 = ensure_utc(start_b), ensure_utc(end_b)
    return a0 < b1 and b0 < a1


def format_slot_label(starts_at: datetime, tz: str = APPOINTMENT_TIMEZONE) -> str:
    """Human-readable label in tenant timezone (America/Sao_Paulo by default)."""
    local = ensure_utc(starts_at).astimezone(ZoneInfo(tz))
    weekday = _WEEKDAY_LABELS_PT[local.weekday()]
    return f"{weekday} {local.strftime('%d/%m/%Y %H:%M')}"


def generate_candidate_slots(
    from_dt: datetime,
    to_dt: datetime,
    *,
    availability: AvailabilityConfig | None = None,
    slot_minutes: int | None = None,
) -> list[tuple[datetime, datetime]]:
    """
    Build UTC slot intervals within [from_dt, to_dt) respecting availability rules.

    Uses the same [start, end) window semantics as ``activation_window``.
    """
    cfg = availability or default_availability()
    minutes = slot_minutes if slot_minutes is not None else cfg.slot_minutes
    if minutes <= 0:
        return []

    tz = ZoneInfo(cfg.timezone)
    range_start = ensure_utc(from_dt)
    range_end = ensure_utc(to_dt)
    if range_end <= range_start:
        return []

    window_start = _parse_hhmm(cfg.start)
    window_end = _parse_hhmm(cfg.end)
    slot_delta = timedelta(minutes=minutes)

    slots: list[tuple[datetime, datetime]] = []
    current_day: date = range_start.astimezone(tz).date()
    last_day: date = range_end.astimezone(tz).date()

    while current_day <= last_day:
        if current_day.weekday() in cfg.weekdays:
            day_start = datetime.combine(current_day, window_start, tzinfo=tz)
            day_end = datetime.combine(current_day, window_end, tzinfo=tz)
            cursor = day_start
            while cursor + slot_delta <= day_end:
                slot_end = cursor + slot_delta
                starts_utc = cursor.astimezone(timezone.utc)
                ends_utc = slot_end.astimezone(timezone.utc)
                if ends_utc > range_start and starts_utc < range_end:
                    slots.append((starts_utc, ends_utc))
                cursor = slot_end
        current_day += timedelta(days=1)

    return slots


def filter_available_slots(
    candidates: list[tuple[datetime, datetime]],
    blocking: list[Appointment],
) -> list[tuple[datetime, datetime]]:
    """Remove candidate slots that overlap active appointments."""
    free: list[tuple[datetime, datetime]] = []
    for starts_at, ends_at in candidates:
        blocked = any(
            intervals_overlap(starts_at, ends_at, appt.starts_at, appt.ends_at)
            for appt in blocking
        )
        if not blocked:
            free.append((starts_at, ends_at))
    return free


def slot_to_dict(
    starts_at: datetime,
    ends_at: datetime,
    *,
    tz: str = APPOINTMENT_TIMEZONE,
) -> dict[str, Any]:
    return {
        "starts_at": ensure_utc(starts_at),
        "ends_at": ensure_utc(ends_at),
        "label": format_slot_label(starts_at, tz=tz),
    }


async def _fetch_blocking_appointments(
    session: AsyncSession,
    user_id: uuid.UUID,
    from_dt: datetime,
    to_dt: datetime,
    *,
    exclude_appointment_id: uuid.UUID | None = None,
) -> list[Appointment]:
    query = select(Appointment).where(
        Appointment.user_id == user_id,
        Appointment.status.in_(ACTIVE_BLOCKING_STATUSES),
        Appointment.starts_at < ensure_utc(to_dt),
        Appointment.ends_at > ensure_utc(from_dt),
    )
    if exclude_appointment_id is not None:
        query = query.where(Appointment.id != exclude_appointment_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def _get_lead_for_tenant(
    session: AsyncSession,
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise AppointmentOwnershipError("Lead not found")
    if lead.user_id != user_id:
        raise AppointmentOwnershipError("Lead does not belong to tenant")
    return lead


async def list_available_slots(
    session: AsyncSession,
    user_id: uuid.UUID,
    from_dt: datetime,
    to_dt: datetime,
    *,
    slot_minutes: int | None = None,
    availability: AvailabilityConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = availability or default_availability()
    effective_minutes = slot_minutes if slot_minutes is not None else cfg.slot_minutes
    candidates = generate_candidate_slots(
        from_dt,
        to_dt,
        availability=cfg,
        slot_minutes=effective_minutes,
    )
    blocking = await _fetch_blocking_appointments(session, user_id, from_dt, to_dt)
    free = filter_available_slots(candidates, blocking)
    return [
        slot_to_dict(starts_at, ends_at, tz=cfg.timezone)
        for starts_at, ends_at in free
    ]


async def create_appointment(
    session: AsyncSession,
    user_id: uuid.UUID,
    lead_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    title: str,
    notes: str | None = None,
    agent_id: uuid.UUID | None = None,
    channel: str | None = None,
    created_by: AppointmentSource | str = AppointmentSource.AGENT,
    status: AppointmentStatus | str = AppointmentStatus.SCHEDULED,
) -> Appointment:
    await _get_lead_for_tenant(session, user_id, lead_id)

    starts_utc = ensure_utc(starts_at)
    ends_utc = ensure_utc(ends_at)
    if ends_utc <= starts_utc:
        raise AppointmentError("ends_at must be after starts_at")

    blocking = await _fetch_blocking_appointments(
        session,
        user_id,
        starts_utc,
        ends_utc,
    )
    for existing in blocking:
        if intervals_overlap(starts_utc, ends_utc, existing.starts_at, existing.ends_at):
            raise AppointmentSlotConflictError(
                "Slot overlaps an existing appointment for this tenant"
            )

    source_value = (
        created_by.value if isinstance(created_by, AppointmentSource) else str(created_by)
    )
    status_value = status.value if isinstance(status, AppointmentStatus) else str(status)
    now = datetime.now(timezone.utc)

    appointment = Appointment(
        user_id=user_id,
        lead_id=lead_id,
        agent_id=agent_id,
        starts_at=starts_utc,
        ends_at=ends_utc,
        title=title.strip(),
        notes=notes,
        status=status_value,
        created_by=source_value,
        channel=channel,
        created_at=now,
        updated_at=now,
    )
    session.add(appointment)
    await session.flush()
    await session.refresh(appointment)
    return appointment


async def cancel_appointment(
    session: AsyncSession,
    user_id: uuid.UUID,
    appointment_id: uuid.UUID,
) -> Appointment:
    appointment = await session.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError("Appointment not found")
    if appointment.user_id != user_id:
        raise AppointmentOwnershipError("Appointment does not belong to tenant")

    appointment.status = AppointmentStatus.CANCELLED.value
    appointment.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(appointment)
    return appointment


async def list_appointments(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    lead_id: uuid.UUID | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    status: AppointmentStatus | str | None = None,
) -> list[Appointment]:
    query = select(Appointment).where(Appointment.user_id == user_id)

    if lead_id is not None:
        query = query.where(Appointment.lead_id == lead_id)
    if from_dt is not None:
        query = query.where(Appointment.ends_at > ensure_utc(from_dt))
    if to_dt is not None:
        query = query.where(Appointment.starts_at < ensure_utc(to_dt))
    if status is not None:
        status_value = status.value if isinstance(status, AppointmentStatus) else str(status)
        query = query.where(Appointment.status == status_value)

    query = query.order_by(Appointment.starts_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_appointment_for_tenant(
    session: AsyncSession,
    user_id: uuid.UUID,
    appointment_id: uuid.UUID,
) -> Appointment:
    appointment = await session.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError("Appointment not found")
    if appointment.user_id != user_id:
        raise AppointmentOwnershipError("Appointment does not belong to tenant")
    return appointment


async def update_appointment(
    session: AsyncSession,
    user_id: uuid.UUID,
    appointment_id: uuid.UUID,
    *,
    status: AppointmentStatus | str | None = None,
    notes: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    unset_notes: bool = False,
) -> Appointment:
    appointment = await get_appointment_for_tenant(session, user_id, appointment_id)

    new_starts = ensure_utc(starts_at) if starts_at is not None else appointment.starts_at
    new_ends = ensure_utc(ends_at) if ends_at is not None else appointment.ends_at
    if new_ends <= new_starts:
        raise AppointmentError("ends_at must be after starts_at")

    rescheduling = (
        starts_at is not None and ensure_utc(starts_at) != appointment.starts_at
    ) or (ends_at is not None and ensure_utc(ends_at) != appointment.ends_at)

    if rescheduling:
        blocking = await _fetch_blocking_appointments(
            session,
            user_id,
            new_starts,
            new_ends,
            exclude_appointment_id=appointment.id,
        )
        for existing in blocking:
            if intervals_overlap(new_starts, new_ends, existing.starts_at, existing.ends_at):
                raise AppointmentSlotConflictError(
                    "Slot overlaps an existing appointment for this tenant"
                )
        appointment.starts_at = new_starts
        appointment.ends_at = new_ends

    if status is not None:
        status_value = status.value if isinstance(status, AppointmentStatus) else str(status)
        appointment.status = status_value

    if unset_notes:
        appointment.notes = None
    elif notes is not None:
        appointment.notes = notes

    appointment.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(appointment)
    return appointment
