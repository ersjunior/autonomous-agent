"""Integração — appointment_service (slots, conflito, ownership, cancelamento)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.appointment import AppointmentSource, AppointmentStatus
from app.services.appointment_service import (
    AppointmentNotFoundError,
    AppointmentOwnershipError,
    AppointmentSlotConflictError,
    cancel_appointment,
    create_appointment,
    list_available_slots,
    list_appointments,
)
from tests.integration.helpers import OwnerContext, create_owner_context

pytestmark = pytest.mark.integration

TZ = ZoneInfo("America/Sao_Paulo")


def _utc(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    local = datetime(y, m, d, h, mi, tzinfo=TZ)
    return local.astimezone(timezone.utc)


async def test_list_available_slots_excludes_existing_appointment(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    day_start = _utc(2026, 6, 17, 0, 0)
    day_end = _utc(2026, 6, 18, 0, 0)

    before = await list_available_slots(
        db_session,
        owner_ctx.user.id,
        day_start,
        day_end,
    )
    assert len(before) == 18

    slot = before[2]
    await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        slot["starts_at"],
        slot["ends_at"],
        title="Demo",
    )

    after = await list_available_slots(
        db_session,
        owner_ctx.user.id,
        day_start,
        day_end,
    )
    assert len(after) == 17
    assert all(
        not (
            s["starts_at"] == slot["starts_at"] and s["ends_at"] == slot["ends_at"]
        )
        for s in after
    )


async def test_create_appointment_persists_utc(owner_ctx: OwnerContext, db_session) -> None:
    starts = _utc(2026, 6, 18, 10, 0)
    ends = _utc(2026, 6, 18, 10, 30)

    appt = await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        starts,
        ends,
        title="Visita técnica",
        channel="whatsapp",
        created_by=AppointmentSource.AGENT,
    )

    assert appt.starts_at.tzinfo is not None
    assert appt.ends_at.tzinfo is not None
    assert appt.starts_at == starts
    assert appt.status == AppointmentStatus.SCHEDULED.value
    assert appt.created_by == AppointmentSource.AGENT.value


async def test_create_appointment_rejects_overlap(owner_ctx: OwnerContext, db_session) -> None:
    starts = _utc(2026, 6, 19, 11, 0)
    ends = _utc(2026, 6, 19, 11, 30)

    await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        starts,
        ends,
        title="Primeiro",
    )

    with pytest.raises(AppointmentSlotConflictError):
        await create_appointment(
            db_session,
            owner_ctx.user.id,
            owner_ctx.lead.id,
            _utc(2026, 6, 19, 11, 15),
            _utc(2026, 6, 19, 11, 45),
            title="Conflito",
        )


async def test_create_appointment_validates_lead_tenant(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    other_ctx = await create_owner_context(db_session, email_suffix="other-lead")

    with pytest.raises(AppointmentOwnershipError):
        await create_appointment(
            db_session,
            owner_ctx.user.id,
            other_ctx.lead.id,
            _utc(2026, 6, 20, 9, 0),
            _utc(2026, 6, 20, 9, 30),
            title="Lead errado",
        )


async def test_cancel_appointment_sets_status(owner_ctx: OwnerContext, db_session) -> None:
    appt = await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        _utc(2026, 6, 21, 14, 0),
        _utc(2026, 6, 21, 14, 30),
        title="Cancelável",
    )

    cancelled = await cancel_appointment(db_session, owner_ctx.user.id, appt.id)
    assert cancelled.status == AppointmentStatus.CANCELLED.value


async def test_cancel_appointment_rejects_other_tenant(
    owner_ctx: OwnerContext,
    second_owner,
    db_session,
) -> None:
    appt = await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        _utc(2026, 6, 22, 15, 0),
        _utc(2026, 6, 22, 15, 30),
        title="Protegido",
    )

    with pytest.raises(AppointmentOwnershipError):
        await cancel_appointment(db_session, second_owner.id, appt.id)


async def test_cancel_nonexistent_raises(owner_ctx: OwnerContext, db_session) -> None:
    with pytest.raises(AppointmentNotFoundError):
        await cancel_appointment(db_session, owner_ctx.user.id, uuid.uuid4())


async def test_list_appointments_filters_by_lead(owner_ctx: OwnerContext, db_session) -> None:
    await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        _utc(2026, 6, 23, 9, 0),
        _utc(2026, 6, 23, 9, 30),
        title="A",
    )
    from app.models.lead import Lead

    second_lead = Lead(
        user_id=owner_ctx.user.id,
        lead_base_id=owner_ctx.lead_base.id,
        nome_cliente="Segundo lead",
        telefone_1="5511888777666",
    )
    db_session.add(second_lead)
    await db_session.flush()

    await create_appointment(
        db_session,
        owner_ctx.user.id,
        second_lead.id,
        _utc(2026, 6, 23, 10, 0),
        _utc(2026, 6, 23, 10, 30),
        title="B",
    )

    rows = await list_appointments(
        db_session,
        owner_ctx.user.id,
        lead_id=owner_ctx.lead.id,
    )
    assert len(rows) == 1
    assert rows[0].lead_id == owner_ctx.lead.id


async def test_slot_label_on_list_available_slots(owner_ctx: OwnerContext, db_session) -> None:
    slots = await list_available_slots(
        db_session,
        owner_ctx.user.id,
        _utc(2026, 6, 17, 0, 0),
        _utc(2026, 6, 18, 0, 0),
    )
    assert slots[0]["label"] == "Qua 17/06/2026 09:00"
