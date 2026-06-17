"""Camada 3 — CRUD + ownership de /appointments via API."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.appointment import Appointment
from app.services.appointment_service import create_appointment

pytestmark = pytest.mark.api

BASE = "/api/v1/appointments/"


def _slot(hour: int, day: int = 10) -> tuple[datetime, datetime]:
    starts = datetime(2026, 7, day, hour, 0, tzinfo=timezone.utc)
    ends = starts + timedelta(minutes=30)
    return starts, ends


def _payload(lead_id: str, starts: datetime, ends: datetime, *, title: str = "Visita") -> dict:
    return {
        "lead_id": lead_id,
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "title": title,
        "notes": "Notas teste",
    }


async def test_appointments_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_appointments_create_manual_and_list(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    starts, ends = _slot(9)
    payload = _payload(str(owner_ctx.lead.id), starts, ends)
    created = await auth_client.post(BASE, json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "Visita"
    assert body["created_by"] == "MANUAL"
    assert body["lead_name"] == owner_ctx.lead.nome_cliente
    assert body["status"] == "SCHEDULED"

    listed = await auth_client.get(BASE)
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert body["id"] in ids


async def test_appointments_create_conflict_returns_409(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    starts, ends = _slot(11, day=11)
    first = await auth_client.post(BASE, json=_payload(str(owner_ctx.lead.id), starts, ends))
    assert first.status_code == 201

    overlap_start = starts + timedelta(minutes=15)
    overlap_end = ends + timedelta(minutes=15)
    second = await auth_client.post(
        BASE,
        json=_payload(str(owner_ctx.lead.id), overlap_start, overlap_end, title="Conflito"),
    )
    assert second.status_code == 409
    assert "conflito" in second.json()["detail"].lower()


async def test_appointments_patch_status(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    starts, ends = _slot(14, day=12)
    created = await auth_client.post(BASE, json=_payload(str(owner_ctx.lead.id), starts, ends))
    appt_id = created.json()["id"]

    updated = await auth_client.patch(
        f"{BASE}{appt_id}",
        json={"status": "CONFIRMED"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "CONFIRMED"


async def test_appointments_cancel_via_patch(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    starts, ends = _slot(15, day=13)
    created = await auth_client.post(BASE, json=_payload(str(owner_ctx.lead.id), starts, ends))
    appt_id = created.json()["id"]

    cancelled = await auth_client.patch(
        f"{BASE}{appt_id}",
        json={"status": "CANCELLED"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


async def test_appointments_list_filter_by_status(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    starts, ends = _slot(16, day=14)
    created = await auth_client.post(BASE, json=_payload(str(owner_ctx.lead.id), starts, ends))
    appt_id = created.json()["id"]
    await auth_client.patch(f"{BASE}{appt_id}", json={"status": "COMPLETED"})

    response = await auth_client.get(f"{BASE}?status=COMPLETED")
    assert response.status_code == 200
    assert all(item["status"] == "COMPLETED" for item in response.json())
    assert any(item["id"] == appt_id for item in response.json())


async def test_appointments_tenant_isolation(
    test_app,
    client,
    owner_ctx,
    db_session,
) -> None:
    from app.core.security import get_current_user
    from app.models.user import User
    from tests.integration.helpers import create_owner_context

    other_ctx = await create_owner_context(db_session, email_suffix="tenant-other")
    foreign_starts, foreign_ends = _slot(12, day=20)
    foreign_appt = await create_appointment(
        db_session,
        other_ctx.user.id,
        other_ctx.lead.id,
        foreign_starts,
        foreign_ends,
        title="Foreign",
    )
    await db_session.flush()
    foreign_id = str(foreign_appt.id)

    owner_user_id = owner_ctx.user.id
    other_user_id = other_ctx.user.id

    async def as_owner():
        async def override_get_current_user():
            user = await db_session.get(User, owner_user_id)
            assert user is not None
            return user

        test_app.dependency_overrides[get_current_user] = override_get_current_user

    async def as_other():
        async def override_get_current_user():
            user = await db_session.get(User, other_user_id)
            assert user is not None
            return user

        test_app.dependency_overrides[get_current_user] = override_get_current_user

    await as_owner()
    own_starts, own_ends = _slot(10, day=15)
    own = await client.post(
        BASE,
        json=_payload(str(owner_ctx.lead.id), own_starts, own_ends),
    )
    assert own.status_code == 201
    own_id = own.json()["id"]

    listed = await client.get(BASE)
    ids = {item["id"] for item in listed.json()}
    assert own_id in ids
    assert foreign_id not in ids

    get_foreign = await client.get(f"{BASE}{foreign_id}")
    assert get_foreign.status_code == 404

    patch_foreign = await client.patch(
        f"{BASE}{foreign_id}",
        json={"status": "CANCELLED"},
    )
    assert patch_foreign.status_code == 404

    await as_other()
    other_list = await client.get(BASE)
    other_ids = {item["id"] for item in other_list.json()}
    assert foreign_id in other_ids
    assert own_id not in other_ids


async def test_appointments_foreign_lead_returns_404(
    auth_client,
    db_session,
) -> None:
    from tests.api.ownership_helpers import foreign_lead_id

    starts, ends = _slot(9, day=16)
    response = await auth_client.post(
        BASE,
        json=_payload(str(await foreign_lead_id(db_session)), starts, ends),
    )
    assert response.status_code == 404
