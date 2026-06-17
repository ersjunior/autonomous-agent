"""Calendar integration tool — internal Postgres agenda (Fase A façade)."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.appointment import AppointmentSource
from app.services.appointment_service import (
    AppointmentError,
    AppointmentOwnershipError,
    AppointmentSlotConflictError,
    AvailabilityConfig,
    create_appointment as svc_create_appointment,
    default_availability,
    list_available_slots as svc_list_available_slots,
)

logger = logging.getLogger(__name__)


def _parse_user_id(user_id: str | uuid.UUID) -> uuid.UUID:
    if isinstance(user_id, uuid.UUID):
        return user_id
    return uuid.UUID(str(user_id).strip())


def _parse_lead_id(lead_id: str | uuid.UUID) -> uuid.UUID:
    if isinstance(lead_id, uuid.UUID):
        return lead_id
    return uuid.UUID(str(lead_id).strip())


def _parse_optional_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    raw = str(value).strip()
    return uuid.UUID(raw) if raw else None


def _appointment_to_dict(appointment: Any) -> dict[str, Any]:
    return {
        "id": str(appointment.id),
        "user_id": str(appointment.user_id),
        "lead_id": str(appointment.lead_id),
        "agent_id": str(appointment.agent_id) if appointment.agent_id else None,
        "starts_at": appointment.starts_at.isoformat(),
        "ends_at": appointment.ends_at.isoformat(),
        "title": appointment.title,
        "notes": appointment.notes,
        "status": appointment.status,
        "created_by": appointment.created_by,
        "channel": appointment.channel,
    }


@asynccontextmanager
async def _session_scope(session: AsyncSession | None):
    """
    API/worker: pass an existing AsyncSession (caller commits).

    Tool standalone: opens AsyncSessionLocal and commits on success.
    """
    if session is not None:
        yield session
        return

    async with AsyncSessionLocal() as owned:
        try:
            yield owned
            await owned.commit()
        except Exception:
            await owned.rollback()
            raise


class CalendarTool:
    """Façade imperativa para consulta de slots e criação de compromissos."""

    async def list_available_slots(
        self,
        user_id: str | uuid.UUID,
        from_dt: datetime,
        to_dt: datetime,
        *,
        slot_minutes: int | None = None,
        availability: AvailabilityConfig | None = None,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        try:
            uid = _parse_user_id(user_id)
            async with _session_scope(session) as db:
                slots = await svc_list_available_slots(
                    db,
                    uid,
                    from_dt,
                    to_dt,
                    slot_minutes=slot_minutes,
                    availability=availability,
                )
                if session is None:
                    # commit handled by _session_scope for read-only is harmless
                    pass
                return slots
        except Exception:
            logger.warning(
                "Calendar list_available_slots failed user_id=%s",
                user_id,
                exc_info=True,
            )
            return []

    async def create_appointment(
        self,
        user_id: str | uuid.UUID,
        lead_id: str | uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        *,
        title: str,
        notes: str | None = None,
        agent_id: str | uuid.UUID | None = None,
        channel: str | None = None,
        created_by: str = AppointmentSource.AGENT.value,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        try:
            uid = _parse_user_id(user_id)
            lid = _parse_lead_id(lead_id)
            aid = _parse_optional_uuid(agent_id)
            source = AppointmentSource(created_by)

            async with _session_scope(session) as db:
                appointment = await svc_create_appointment(
                    db,
                    uid,
                    lid,
                    starts_at,
                    ends_at,
                    title=title,
                    notes=notes,
                    agent_id=aid,
                    channel=channel,
                    created_by=source,
                )
                if session is not None:
                    await db.flush()
                return {"ok": True, "appointment": _appointment_to_dict(appointment)}
        except AppointmentSlotConflictError as exc:
            logger.info(
                "Calendar create_appointment slot conflict user_id=%s lead_id=%s",
                user_id,
                lead_id,
            )
            return {"ok": False, "error": "slot_conflict", "message": str(exc)}
        except AppointmentOwnershipError as exc:
            logger.warning(
                "Calendar create_appointment ownership error user_id=%s lead_id=%s",
                user_id,
                lead_id,
            )
            return {"ok": False, "error": "ownership", "message": str(exc)}
        except (AppointmentError, ValueError) as exc:
            logger.warning(
                "Calendar create_appointment validation error user_id=%s: %s",
                user_id,
                exc,
            )
            return {"ok": False, "error": "validation", "message": str(exc)}
        except Exception:
            logger.warning(
                "Calendar create_appointment failed user_id=%s lead_id=%s",
                user_id,
                lead_id,
                exc_info=True,
            )
            return {"ok": False, "error": "internal", "message": "Could not create appointment"}


_calendar = CalendarTool()


async def list_available_slots(
    user_id: str | uuid.UUID,
    from_dt: datetime,
    to_dt: datetime,
    *,
    slot_minutes: int | None = None,
    availability: AvailabilityConfig | None = None,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """Atalho de módulo — espelha ``retrieve_kb_chunks`` da knowledge base."""
    return await _calendar.list_available_slots(
        user_id,
        from_dt,
        to_dt,
        slot_minutes=slot_minutes,
        availability=availability or default_availability(),
        session=session,
    )


async def create_appointment(
    user_id: str | uuid.UUID,
    lead_id: str | uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    title: str,
    notes: str | None = None,
    agent_id: str | uuid.UUID | None = None,
    channel: str | None = None,
    created_by: str = AppointmentSource.AGENT.value,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Atalho de módulo — retorna dict estruturado (ok/error), sem propagar exceção ao grafo."""
    return await _calendar.create_appointment(
        user_id,
        lead_id,
        starts_at,
        ends_at,
        title=title,
        notes=notes,
        agent_id=agent_id,
        channel=channel,
        created_by=created_by,
        session=session,
    )
