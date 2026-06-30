"""Unit tests — janelas de detecção de lembrete de agendamento."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.appointment_reminder_service import (
    is_in_due_window,
    is_in_reminder_window,
    reminder_window_bounds,
)

_NOW = datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc)


def test_reminder_window_bounds() -> None:
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    window_start, window_end = reminder_window_bounds(
        starts, lead_minutes=30, grace_minutes=5
    )
    assert window_start == datetime(2026, 6, 30, 14, 30, tzinfo=timezone.utc)
    assert window_end == datetime(2026, 6, 30, 14, 55, tzinfo=timezone.utc)


def test_is_in_reminder_window_inside() -> None:
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 30, 14, 45, tzinfo=timezone.utc)
    assert is_in_reminder_window(starts, now, lead_minutes=30, grace_minutes=5)


def test_is_in_reminder_window_too_close_skipped() -> None:
    """Menos de 5 min antes do horário — fora da janela de lembrete."""
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 30, 14, 58, tzinfo=timezone.utc)
    assert not is_in_reminder_window(starts, now, lead_minutes=30, grace_minutes=5)


def test_is_in_reminder_window_too_early() -> None:
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 30, 14, 20, tzinfo=timezone.utc)
    assert not is_in_reminder_window(starts, now, lead_minutes=30, grace_minutes=5)


def test_is_in_due_window_inside() -> None:
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 30, 15, 10, tzinfo=timezone.utc)
    assert is_in_due_window(starts, now, tolerance_minutes=15)


def test_is_in_due_window_too_late() -> None:
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 30, 15, 20, tzinfo=timezone.utc)
    assert not is_in_due_window(starts, now, tolerance_minutes=15)


def test_is_in_due_window_before_start() -> None:
    starts = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 30, 14, 50, tzinfo=timezone.utc)
    assert not is_in_due_window(starts, now, tolerance_minutes=15)
