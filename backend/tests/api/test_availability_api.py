"""Camada 3 — API de disponibilidade (grade semanal tenant + agente)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.availability_rule import AvailabilityRule
from tests.api.ownership_helpers import foreign_agent_id

pytestmark = pytest.mark.api

TENANT_BASE = "/api/v1/availability-rules"
AGENTS = "/api/v1/agents"


def _day(weekday: int, start: str = "09:00", end: str = "12:00", **kwargs) -> dict:
    payload = {"weekday": weekday, "start_time": start, "end_time": end}
    payload.update(kwargs)
    return payload


async def test_tenant_availability_get_empty(auth_client) -> None:
    response = await auth_client.get(TENANT_BASE)
    assert response.status_code == 200
    assert response.json() == []


async def test_tenant_availability_put_and_get(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    body = {"days": [_day(0), _day(1, "10:00", "14:00", slot_minutes=60)]}
    put = await auth_client.put(TENANT_BASE, json=body)
    assert put.status_code == 200
    saved = put.json()
    assert len(saved) == 2
    assert {row["weekday"] for row in saved} == {0, 1}
    assert saved[0]["agent_id"] is None

    get = await auth_client.get(TENANT_BASE)
    assert get.status_code == 200
    assert len(get.json()) == 2


async def test_agent_availability_isolated_from_tenant(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    tenant_body = {"days": [_day(2, "09:00", "12:00")]}
    agent_body = {"days": [_day(2, "14:00", "18:00")]}

    assert (await auth_client.put(TENANT_BASE, json=tenant_body)).status_code == 200
    agent_url = f"{AGENTS}/{owner_ctx.agent.id}/availability-rules"
    assert (await auth_client.put(agent_url, json=agent_body)).status_code == 200

    tenant_rows = (await auth_client.get(TENANT_BASE)).json()
    agent_rows = (await auth_client.get(agent_url)).json()
    assert tenant_rows[0]["start_time"] == "09:00"
    assert agent_rows[0]["start_time"] == "14:00"


async def test_agent_availability_foreign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = await foreign_agent_id(db_session)
    url = f"{AGENTS}/{foreign_id}/availability-rules"
    assert (await auth_client.get(url)).status_code == 404
    assert (
        await auth_client.put(url, json={"days": [_day(0)]})
    ).status_code == 404


async def test_tenant_availability_requires_auth(client) -> None:
    assert (await client.get(TENANT_BASE)).status_code == 401


async def test_tenant_availability_invalid_weekday_returns_422(auth_client) -> None:
    response = await auth_client.put(
        TENANT_BASE,
        json={"days": [_day(7, "09:00", "12:00")]},
    )
    assert response.status_code == 422


async def test_tenant_availability_start_not_before_end_returns_422(auth_client) -> None:
    response = await auth_client.put(
        TENANT_BASE,
        json={"days": [_day(0, "18:00", "09:00")]},
    )
    assert response.status_code == 422


async def test_tenant_availability_invalid_slot_minutes_returns_422(auth_client) -> None:
    response = await auth_client.put(
        TENANT_BASE,
        json={"days": [_day(0, slot_minutes=0)]},
    )
    assert response.status_code == 422


async def test_tenant_availability_replace_all_clears_previous(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    first = {"days": [_day(0), _day(1)]}
    second = {"days": [_day(3)]}
    assert (await auth_client.put(TENANT_BASE, json=first)).status_code == 200
    assert (await auth_client.put(TENANT_BASE, json=second)).status_code == 200

    rows = (
        await db_session.execute(
            select(AvailabilityRule).where(
                AvailabilityRule.user_id == owner_ctx.user.id,
                AvailabilityRule.agent_id.is_(None),
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].weekday == 3


async def test_agent_put_persists_for_scope(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    agent_url = f"{AGENTS}/{owner_ctx.agent.id}/availability-rules"
    put = await auth_client.put(agent_url, json={"days": [_day(5, "09:00", "12:00")]})
    assert put.status_code == 200

    row = (
        await db_session.execute(
            select(AvailabilityRule).where(
                AvailabilityRule.user_id == owner_ctx.user.id,
                AvailabilityRule.agent_id == owner_ctx.agent.id,
            )
        )
    ).scalar_one()
    assert row.weekday == 5
