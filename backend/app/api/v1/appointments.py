"""Appointment CRUD API routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.appointment import Appointment, AppointmentSource
from app.models.lead import Lead
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentRead, AppointmentUpdate
from app.services.appointment_service import (
    AppointmentError,
    AppointmentNotFoundError,
    AppointmentOwnershipError,
    AppointmentSlotConflictError,
    cancel_appointment,
    create_appointment,
    get_appointment_for_tenant,
    list_appointments,
    update_appointment,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _parse_query_datetime(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if len(raw) == 10:
        raw = f"{raw}T00:00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _appointment_to_read(appointment: Appointment, lead_name: str | None = None) -> AppointmentRead:
    name = lead_name
    if name is None and appointment.lead is not None:
        name = appointment.lead.nome_cliente
    return AppointmentRead(
        id=appointment.id,
        user_id=appointment.user_id,
        lead_id=appointment.lead_id,
        lead_name=name,
        agent_id=appointment.agent_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        title=appointment.title,
        notes=appointment.notes,
        status=appointment.status,
        created_by=appointment.created_by,
        channel=appointment.channel,
        created_at=appointment.created_at,
        updated_at=appointment.updated_at,
    )


async def _load_appointment_with_lead(
    appointment_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Appointment:
    result = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.lead))
        .where(Appointment.id == appointment_id, Appointment.user_id == user.id)
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado",
        )
    return appointment


def _map_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AppointmentNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado",
        )
    if isinstance(exc, AppointmentOwnershipError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado",
        )
    if isinstance(exc, AppointmentSlotConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Horário indisponível — conflito com outro agendamento",
        )
    if isinstance(exc, AppointmentError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.get("/", response_model=list[AppointmentRead])
async def list_appointments_route(
    lead_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    from_dt: str | None = Query(None, alias="from"),
    to_dt: str | None = Query(None, alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AppointmentRead]:
    rows = await list_appointments(
        db,
        user.id,
        lead_id=lead_id,
        from_dt=_parse_query_datetime(from_dt),
        to_dt=_parse_query_datetime(to_dt),
        status=status_filter,
    )
    if not rows:
        return []

    lead_ids = {row.lead_id for row in rows}
    lead_result = await db.execute(select(Lead).where(Lead.id.in_(lead_ids)))
    leads_by_id = {lead.id: lead.nome_cliente for lead in lead_result.scalars().all()}

    return [
        _appointment_to_read(row, lead_name=leads_by_id.get(row.lead_id))
        for row in rows
    ]


@router.post("/", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def create_appointment_route(
    payload: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppointmentRead:
    try:
        appointment = await create_appointment(
            db,
            user.id,
            payload.lead_id,
            payload.starts_at,
            payload.ends_at,
            title=payload.title,
            notes=payload.notes,
            created_by=AppointmentSource.MANUAL,
        )
        await db.commit()
        await db.refresh(appointment)
        lead = await db.get(Lead, payload.lead_id)
        return _appointment_to_read(appointment, lead_name=lead.nome_cliente if lead else None)
    except (AppointmentError, AppointmentOwnershipError, AppointmentSlotConflictError) as exc:
        await db.rollback()
        raise _map_service_error(exc) from exc


@router.get("/{appointment_id}", response_model=AppointmentRead)
async def get_appointment_route(
    appointment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppointmentRead:
    appointment = await _load_appointment_with_lead(appointment_id, user, db)
    return _appointment_to_read(appointment)


@router.patch("/{appointment_id}", response_model=AppointmentRead)
async def update_appointment_route(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppointmentRead:
    data = payload.model_dump(exclude_unset=True)
    notes_provided = "notes" in data
    try:
        if data.get("status") == "CANCELLED" and len(data) == 1:
            appointment = await cancel_appointment(db, user.id, appointment_id)
        else:
            appointment = await update_appointment(
                db,
                user.id,
                appointment_id,
                status=data.get("status"),
                notes=data.get("notes") if notes_provided else None,
                starts_at=data.get("starts_at"),
                ends_at=data.get("ends_at"),
                unset_notes=notes_provided and data.get("notes") is None,
            )
        await db.commit()
        appointment = await _load_appointment_with_lead(appointment_id, user, db)
        return _appointment_to_read(appointment)
    except (AppointmentError, AppointmentNotFoundError, AppointmentOwnershipError, AppointmentSlotConflictError) as exc:
        await db.rollback()
        raise _map_service_error(exc) from exc
