"""CRUD de regras de disponibilidade (Fase D4) — leitura/escrita da grade semanal."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activation_window import _parse_hhmm
from app.models.availability_rule import AvailabilityRule

_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


class AvailabilityValidationError(ValueError):
    """Payload inválido para a grade de disponibilidade."""


@dataclass(frozen=True)
class AvailabilityDayPayload:
    weekday: int
    start_time: str
    end_time: str
    slot_minutes: int | None = None
    timezone: str | None = None


def _validate_hhmm(value: str, *, field: str) -> str:
    raw = value.strip()
    if not _HHMM_RE.match(raw):
        raise AvailabilityValidationError(f"{field} deve estar no formato HH:MM")
    try:
        _parse_hhmm(raw)
    except (ValueError, IndexError) as exc:
        raise AvailabilityValidationError(f"{field} inválido: {value}") from exc
    return raw


def _validate_day_payload(day: AvailabilityDayPayload) -> AvailabilityDayPayload:
    if day.weekday < 0 or day.weekday > 6:
        raise AvailabilityValidationError("weekday deve estar entre 0 (segunda) e 6 (domingo)")

    start = _validate_hhmm(day.start_time, field="start_time")
    end = _validate_hhmm(day.end_time, field="end_time")
    if _parse_hhmm(start) >= _parse_hhmm(end):
        raise AvailabilityValidationError("start_time deve ser anterior a end_time")

    if day.slot_minutes is not None and day.slot_minutes <= 0:
        raise AvailabilityValidationError("slot_minutes deve ser maior que zero")

    tz = day.timezone.strip() if day.timezone else None
    if tz == "":
        tz = None

    return AvailabilityDayPayload(
        weekday=day.weekday,
        start_time=start,
        end_time=end,
        slot_minutes=day.slot_minutes,
        timezone=tz,
    )


async def get_availability_rules(
    session: AsyncSession,
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
) -> list[AvailabilityRule]:
    """Lista regras do escopo (tenant: agent_id NULL; agente: agent_id preenchido)."""
    result = await session.execute(
        select(AvailabilityRule)
        .where(
            AvailabilityRule.user_id == user_id,
            AvailabilityRule.agent_id == agent_id,
        )
        .order_by(AvailabilityRule.weekday.asc())
    )
    return list(result.scalars().all())


async def replace_availability_rules(
    session: AsyncSession,
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    rules: list[AvailabilityDayPayload],
) -> list[AvailabilityRule]:
    """
    Substitui a grade inteira do escopo (REPLACE-ALL).

    Remove todas as regras de (user_id, agent_id) e insere apenas os dias ativos enviados.
    """
    seen_weekdays: set[int] = set()
    validated: list[AvailabilityDayPayload] = []
    for raw in rules:
        day = _validate_day_payload(raw)
        if day.weekday in seen_weekdays:
            raise AvailabilityValidationError("weekday duplicado na grade")
        seen_weekdays.add(day.weekday)
        validated.append(day)

    await session.execute(
        delete(AvailabilityRule).where(
            AvailabilityRule.user_id == user_id,
            AvailabilityRule.agent_id == agent_id,
        )
    )

    now = datetime.now(timezone.utc)
    created: list[AvailabilityRule] = []
    for day in validated:
        row = AvailabilityRule(
            user_id=user_id,
            agent_id=agent_id,
            weekday=day.weekday,
            start_time=day.start_time,
            end_time=day.end_time,
            slot_minutes=day.slot_minutes,
            timezone=day.timezone,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        created.append(row)

    await session.flush()
    for row in created:
        await session.refresh(row)
    return sorted(created, key=lambda r: r.weekday)
