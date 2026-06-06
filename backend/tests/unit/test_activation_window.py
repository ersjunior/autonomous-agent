"""Testes unitários — janela operacional do motor de acionamento."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.core.activation_window import _parse_hhmm, is_within_window

TZ = ZoneInfo("America/Sao_Paulo")
pytestmark = pytest.mark.unit


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 6, 4, hour, minute, tzinfo=TZ)


class TestIsWithinWindowSameDay:
    def test_inside_window(self) -> None:
        assert is_within_window("09:00", "20:00", now=_dt(10, 0), tz="America/Sao_Paulo")

    def test_outside_before_start(self) -> None:
        assert not is_within_window("09:00", "20:00", now=_dt(8, 59), tz="America/Sao_Paulo")

    def test_start_boundary_inclusive(self) -> None:
        assert is_within_window("09:00", "20:00", now=_dt(9, 0), tz="America/Sao_Paulo")

    def test_end_boundary_exclusive(self) -> None:
        assert not is_within_window("09:00", "20:00", now=_dt(20, 0), tz="America/Sao_Paulo")

    def test_narrow_window_outside(self) -> None:
        assert not is_within_window("02:00", "03:00", now=_dt(14, 0), tz="America/Sao_Paulo")


class TestIsWithinWindowMidnightCrossing:
    def test_late_night_inside(self) -> None:
        assert is_within_window("22:00", "06:00", now=_dt(23, 30), tz="America/Sao_Paulo")

    def test_early_morning_inside(self) -> None:
        assert is_within_window("22:00", "06:00", now=_dt(3, 0), tz="America/Sao_Paulo")

    def test_afternoon_outside(self) -> None:
        assert not is_within_window("22:00", "06:00", now=_dt(14, 0), tz="America/Sao_Paulo")

    def test_gap_between_end_and_start_outside(self) -> None:
        assert not is_within_window("22:00", "06:00", now=_dt(12, 0), tz="America/Sao_Paulo")


class TestIsWithinWindowFullDay:
    def test_midday_always_inside(self) -> None:
        assert is_within_window("00:00", "23:59", now=_dt(14, 0), tz="America/Sao_Paulo")

    def test_midnight_inside(self) -> None:
        assert is_within_window("00:00", "23:59", now=_dt(0, 0), tz="America/Sao_Paulo")

    def test_last_included_minute(self) -> None:
        # [inicio, fim) — 23:59 é exclusivo; 23:58 ainda está dentro
        assert is_within_window("00:00", "23:59", now=_dt(23, 58), tz="America/Sao_Paulo")
        assert not is_within_window("00:00", "23:59", now=_dt(23, 59), tz="America/Sao_Paulo")


class TestParseHhmm:
    def test_valid_formats(self) -> None:
        assert _parse_hhmm("09:00") == time(9, 0)
        assert _parse_hhmm(" 23:59 ") == time(23, 59)
        assert _parse_hhmm("00:00") == time(0, 0)

    @pytest.mark.parametrize("value", ["", "abc", "9", "25:00"])
    def test_invalid_formats_raise(self, value: str) -> None:
        with pytest.raises((ValueError, IndexError)):
            _parse_hhmm(value)
