"""Testes unitários — geração de slots e labels de agendamento."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.config import APPOINTMENT_TIMEZONE
from app.models.appointment import Appointment, AppointmentStatus
from app.services.appointment_service import (
    AvailabilityConfig,
    filter_available_slots,
    format_slot_label,
    generate_candidate_slots,
    intervals_overlap,
)

pytestmark = pytest.mark.unit

TZ = ZoneInfo(APPOINTMENT_TIMEZONE)


def _utc(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    local = datetime(y, m, d, h, mi, tzinfo=TZ)
    return local.astimezone(timezone.utc)


class TestGenerateCandidateSlots:
    def test_weekday_slots_within_business_hours(self) -> None:
        # 2026-06-17 is Wednesday
        from_dt = _utc(2026, 6, 17, 8, 0)
        to_dt = _utc(2026, 6, 17, 19, 0)
        slots = generate_candidate_slots(
            from_dt,
            to_dt,
            availability=AvailabilityConfig(slot_minutes=30),
        )
        assert len(slots) == 18  # 09:00–18:00, 30 min
        first_start, first_end = slots[0]
        assert first_start.astimezone(TZ).hour == 9
        assert first_start.astimezone(TZ).minute == 0
        last_start, last_end = slots[-1]
        assert last_start.astimezone(TZ).hour == 17
        assert last_start.astimezone(TZ).minute == 30
        assert last_end.astimezone(TZ).hour == 18

    def test_excludes_weekends(self) -> None:
        # Sat 2026-06-20 through Mon 2026-06-22
        from_dt = _utc(2026, 6, 20, 0, 0)
        to_dt = _utc(2026, 6, 23, 0, 0)
        slots = generate_candidate_slots(from_dt, to_dt)
        for starts_at, _ in slots:
            local = starts_at.astimezone(TZ)
            assert local.weekday() < 5

    def test_respects_slot_minutes(self) -> None:
        from_dt = _utc(2026, 6, 17, 9, 0)
        to_dt = _utc(2026, 6, 17, 12, 0)
        slots = generate_candidate_slots(
            from_dt,
            to_dt,
            availability=AvailabilityConfig(slot_minutes=60),
        )
        assert len(slots) == 3
        assert (slots[0][1] - slots[0][0]).total_seconds() == 3600

    def test_empty_when_range_invalid(self) -> None:
        from_dt = _utc(2026, 6, 17, 12, 0)
        to_dt = _utc(2026, 6, 17, 9, 0)
        assert generate_candidate_slots(from_dt, to_dt) == []


class TestFilterAvailableSlots:
    def test_subtracts_blocking_appointments(self) -> None:
        candidates = [
            (_utc(2026, 6, 17, 9, 0), _utc(2026, 6, 17, 9, 30)),
            (_utc(2026, 6, 17, 9, 30), _utc(2026, 6, 17, 10, 0)),
            (_utc(2026, 6, 17, 10, 0), _utc(2026, 6, 17, 10, 30)),
        ]
        blocking = [
            Appointment(
                starts_at=_utc(2026, 6, 17, 9, 30),
                ends_at=_utc(2026, 6, 17, 10, 0),
                status=AppointmentStatus.CONFIRMED.value,
                title="x",
                created_by="AGENT",
                user_id=None,  # type: ignore[arg-type]
                lead_id=None,  # type: ignore[arg-type]
            )
        ]
        free = filter_available_slots(candidates, blocking)
        assert len(free) == 2
        assert free[0][0] == candidates[0][0]
        assert free[1][0] == candidates[2][0]


class TestFormatSlotLabel:
    def test_label_in_sao_paulo_timezone(self) -> None:
        # 2026-06-17 14:00 BRT = 17:00 UTC
        starts_at = datetime(2026, 6, 17, 17, 0, tzinfo=timezone.utc)
        label = format_slot_label(starts_at)
        assert label == "Qua 17/06/2026 14:00"


class TestIntervalsOverlap:
    def test_overlap_detected(self) -> None:
        a0 = _utc(2026, 6, 17, 9, 0)
        a1 = _utc(2026, 6, 17, 10, 0)
        b0 = _utc(2026, 6, 17, 9, 30)
        b1 = _utc(2026, 6, 17, 10, 30)
        assert intervals_overlap(a0, a1, b0, b1)

    def test_adjacent_no_overlap(self) -> None:
        a0 = _utc(2026, 6, 17, 9, 0)
        a1 = _utc(2026, 6, 17, 9, 30)
        b0 = _utc(2026, 6, 17, 9, 30)
        b1 = _utc(2026, 6, 17, 10, 0)
        assert not intervals_overlap(a0, a1, b0, b1)
