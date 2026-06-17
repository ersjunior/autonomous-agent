"""Integração — list_available_slots com resolve_availability (Fase D3)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from agents.tools.calendar_tool import list_available_slots as calendar_list_slots
from app.models.availability_rule import AvailabilityRule
from app.services.appointment_service import list_available_slots
from tests.integration.helpers import OwnerContext

pytestmark = pytest.mark.integration

TZ = ZoneInfo("America/Sao_Paulo")


def _utc(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    local = datetime(y, m, d, h, mi, tzinfo=TZ)
    return local.astimezone(timezone.utc)


async def test_list_available_slots_without_rules_unchanged(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    """Retrocompatibilidade: sem regras no banco, comportamento idêntico ao default."""
    day_start = _utc(2026, 6, 17, 0, 0)
    day_end = _utc(2026, 6, 18, 0, 0)

    slots = await list_available_slots(
        db_session,
        owner_ctx.user.id,
        day_start,
        day_end,
        agent_id=owner_ctx.agent.id,
    )
    assert len(slots) == 18
    assert slots[0]["label"] == "Qua 17/06/2026 09:00"


async def test_list_available_slots_tenant_saturday_rule(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    """Regra de tenant habilita sábado com janela própria."""
    rule = AvailabilityRule(
        id=uuid.uuid4(),
        user_id=owner_ctx.user.id,
        agent_id=None,
        weekday=5,  # sábado
        start_time="09:00",
        end_time="12:00",
        slot_minutes=60,
        timezone=None,
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    sat_start = _utc(2026, 6, 20, 0, 0)
    sat_end = _utc(2026, 6, 21, 0, 0)
    slots = await list_available_slots(
        db_session,
        owner_ctx.user.id,
        sat_start,
        sat_end,
        agent_id=owner_ctx.agent.id,
    )
    assert len(slots) == 3
    for slot in slots:
        local = slot["starts_at"].astimezone(TZ)
        assert local.weekday() == 5
        assert local.hour < 12


async def test_list_available_slots_agent_rule_overrides_tenant(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    """Regra do agente substitui a do tenant no mesmo weekday."""
    tenant_rule = AvailabilityRule(
        id=uuid.uuid4(),
        user_id=owner_ctx.user.id,
        agent_id=None,
        weekday=0,
        start_time="10:00",
        end_time="12:00",
        slot_minutes=60,
        timezone=None,
        is_active=True,
    )
    agent_rule = AvailabilityRule(
        id=uuid.uuid4(),
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        weekday=0,
        start_time="09:00",
        end_time="10:30",
        slot_minutes=30,
        timezone=None,
        is_active=True,
    )
    db_session.add_all([tenant_rule, agent_rule])
    await db_session.flush()

    mon_start = _utc(2026, 6, 15, 0, 0)
    mon_end = _utc(2026, 6, 16, 0, 0)
    slots = await list_available_slots(
        db_session,
        owner_ctx.user.id,
        mon_start,
        mon_end,
        agent_id=owner_ctx.agent.id,
    )
    assert len(slots) == 3  # 09:00, 09:30, 10:00 (fim 10:30)
    first = slots[0]["starts_at"].astimezone(TZ)
    assert first.hour == 9
    assert first.minute == 0


@pytest.mark.asyncio
async def test_calendar_tool_invalid_agent_id_falls_back_gracefully(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    """agent_id inválido na façade não quebra — cai para tenant/default."""
    day_start = _utc(2026, 6, 17, 0, 0)
    day_end = _utc(2026, 6, 18, 0, 0)
    slots = await calendar_list_slots(
        str(owner_ctx.user.id),
        day_start,
        day_end,
        agent_id="not-a-valid-uuid",
        session=db_session,
    )
    assert len(slots) == 18


@pytest.mark.asyncio
async def test_calendar_tool_agent_id_string_accepted(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    """agent_id como string UUID é aceito na façade."""
    day_start = _utc(2026, 6, 17, 0, 0)
    day_end = _utc(2026, 6, 18, 0, 0)
    slots = await calendar_list_slots(
        str(owner_ctx.user.id),
        day_start,
        day_end,
        agent_id=str(owner_ctx.agent.id),
        session=db_session,
    )
    assert len(slots) == 18
