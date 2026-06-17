"""Integração — resolução de disponibilidade (Fase D2)."""

from __future__ import annotations

import uuid

import pytest

from app.models.availability_rule import AvailabilityRule
from app.services.appointment_service import (
    default_availability,
    resolve_availability,
    schedule_from_config,
)
from tests.integration.helpers import OwnerContext

pytestmark = pytest.mark.integration


async def test_resolve_availability_defaults_when_no_rules(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    resolved = await resolve_availability(db_session, owner_ctx.user.id, owner_ctx.agent.id)
    expected = schedule_from_config(default_availability())
    assert resolved == expected


async def test_resolve_availability_uses_tenant_rules_when_present(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    rule = AvailabilityRule(
        id=uuid.uuid4(),
        user_id=owner_ctx.user.id,
        agent_id=None,
        weekday=0,  # segunda
        start_time="10:00",
        end_time="12:00",
        slot_minutes=60,
        timezone=None,
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    resolved = await resolve_availability(db_session, owner_ctx.user.id, owner_ctx.agent.id)
    assert set(resolved.rules.keys()) == {0}
    assert resolved.rules[0].start == "10:00"
    assert resolved.rules[0].end == "12:00"
    assert resolved.rules[0].slot_minutes == 60


async def test_resolve_availability_agent_rules_take_precedence_over_tenant(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
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
        end_time="11:00",
        slot_minutes=30,
        timezone=None,
        is_active=True,
    )
    db_session.add_all([tenant_rule, agent_rule])
    await db_session.flush()

    resolved = await resolve_availability(db_session, owner_ctx.user.id, owner_ctx.agent.id)
    assert set(resolved.rules.keys()) == {0}
    assert resolved.rules[0].start == "09:00"
    assert resolved.rules[0].end == "11:00"
    assert resolved.rules[0].slot_minutes == 30

