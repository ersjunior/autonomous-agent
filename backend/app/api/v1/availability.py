"""Availability rules API — weekly schedule per tenant or per agent (Fase D4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent import Agent
from app.models.user import User
from app.schemas.availability import (
    AvailabilityRuleRead,
    AvailabilityScheduleUpdate,
)
from app.services.availability_service import (
    AvailabilityDayPayload,
    AvailabilityValidationError,
    get_availability_rules,
    replace_availability_rules,
)

router = APIRouter(tags=["availability"])


def _rule_to_read(rule) -> AvailabilityRuleRead:
    return AvailabilityRuleRead.model_validate(rule)


def _payload_from_update(body: AvailabilityScheduleUpdate) -> list[AvailabilityDayPayload]:
    return [
        AvailabilityDayPayload(
            weekday=day.weekday,
            start_time=day.start_time,
            end_time=day.end_time,
            slot_minutes=day.slot_minutes,
            timezone=day.timezone,
        )
        for day in body.days
    ]


async def _get_agent(agent_id: uuid.UUID, user: User, db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    raise_if_cannot_view(agent, user, not_found_detail="Agent not found")
    return agent


@router.get("/availability-rules", response_model=list[AvailabilityRuleRead])
async def get_tenant_availability_rules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AvailabilityRuleRead]:
    rows = await get_availability_rules(db, user.id, agent_id=None)
    return [_rule_to_read(row) for row in rows]


@router.put("/availability-rules", response_model=list[AvailabilityRuleRead])
async def put_tenant_availability_rules(
    payload: AvailabilityScheduleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AvailabilityRuleRead]:
    try:
        rows = await replace_availability_rules(
            db,
            user.id,
            None,
            _payload_from_update(payload),
        )
        await db.commit()
        return [_rule_to_read(row) for row in rows]
    except AvailabilityValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/agents/{agent_id}/availability-rules",
    response_model=list[AvailabilityRuleRead],
)
async def get_agent_availability_rules(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AvailabilityRuleRead]:
    agent = await _get_agent(agent_id, user, db)
    rows = await get_availability_rules(db, user.id, agent_id=agent.id)
    return [_rule_to_read(row) for row in rows]


@router.put(
    "/agents/{agent_id}/availability-rules",
    response_model=list[AvailabilityRuleRead],
)
async def put_agent_availability_rules(
    agent_id: uuid.UUID,
    payload: AvailabilityScheduleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AvailabilityRuleRead]:
    agent = await _get_agent(agent_id, user, db)
    raise_if_cannot_edit(agent, user)
    try:
        rows = await replace_availability_rules(
            db,
            user.id,
            agent.id,
            _payload_from_update(payload),
        )
        await db.commit()
        return [_rule_to_read(row) for row in rows]
    except AvailabilityValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
