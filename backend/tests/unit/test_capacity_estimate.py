"""Testes unitários — cálculo de capacidade (R-C) com snapshot injetado."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.capacity_estimate import (
    ResourceSnapshot,
    _resource_units_budget,
    channel_costs,
    estimate_capacity,
)

pytestmark = pytest.mark.unit


def _snapshot(
    *,
    cpu_cores: float = 4.0,
    cpu_available_ratio: float = 0.5,
    ram_available_mb: float = 1024.0,
    ram_total_mb: float = 2048.0,
    gpu: bool = False,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu_cores=cpu_cores,
        cpu_percent_used=50.0,
        cpu_available_ratio=cpu_available_ratio,
        ram_total_mb=ram_total_mb,
        ram_available_mb=ram_available_mb,
        gpu_signal_available=gpu,
        gpu_signal_source="sadtalker_health" if gpu else None,
        gpu_device_name="test-gpu" if gpu else None,
    )


@pytest.fixture
def capacity_coefficients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "capacity_cpu_units_per_core", 10.0)
    monkeypatch.setattr(settings, "capacity_mb_per_unit", 512.0)
    monkeypatch.setattr(settings, "gpu_capacity_boost", 1.15)
    monkeypatch.setattr(settings, "channel_cost_whatsapp", 1.0)
    monkeypatch.setattr(settings, "channel_cost_telegram", 1.0)
    monkeypatch.setattr(settings, "channel_cost_voice", 3.0)
    monkeypatch.setattr(settings, "channel_cost_video", 5.0)


def test_resource_units_budget_arithmetic(capacity_coefficients: None) -> None:
    res = _snapshot(cpu_available_ratio=0.5, cpu_cores=4.0, ram_available_mb=1024.0)
    cpu_units = 0.5 * 4.0 * 10.0
    ram_units = 1024.0 / 512.0
    assert _resource_units_budget(res) == pytest.approx(min(cpu_units, ram_units))


def test_resource_units_budget_gpu_boost(capacity_coefficients: None) -> None:
    base = _snapshot(gpu=False)
    boosted = _snapshot(gpu=True)
    assert _resource_units_budget(boosted) == pytest.approx(
        _resource_units_budget(base) * 1.15,
    )


def test_estimate_capacity_with_fixed_snapshot(capacity_coefficients: None) -> None:
    res = _snapshot(cpu_available_ratio=0.5, cpu_cores=4.0, ram_available_mb=1024.0)
    est = estimate_capacity(resources=res)
    assert est.resource_units_budget == pytest.approx(2.0)
    assert est.max_weighted_capacity == 2
    assert est.channels_if_single_family["whatsapp"] == 2
    assert est.channels_if_single_family["voice"] == 0
    assert est.channels_if_single_family["video"] == 0


def test_channel_costs_match_settings(capacity_coefficients: None) -> None:
    costs = channel_costs()
    assert costs == {
        "whatsapp": 1.0,
        "telegram": 1.0,
        "voice": 3.0,
        "video": 5.0,
    }


def test_more_ram_increases_capacity(capacity_coefficients: None) -> None:
    low = estimate_capacity(resources=_snapshot(ram_available_mb=512.0))
    high = estimate_capacity(resources=_snapshot(ram_available_mb=4096.0))
    assert high.resource_units_budget > low.resource_units_budget
    assert high.max_weighted_capacity > low.max_weighted_capacity


def test_zero_resources_floor_at_minimum(capacity_coefficients: None) -> None:
    res = _snapshot(cpu_available_ratio=0.0, ram_available_mb=0.0)
    est = estimate_capacity(resources=res)
    assert est.resource_units_budget == 0.0
    assert est.max_weighted_capacity == 1


def test_ram_bound_channel_counts(capacity_coefficients: None) -> None:
    res = _snapshot(ram_available_mb=2560.0, cpu_available_ratio=1.0, cpu_cores=100.0)
    est = estimate_capacity(resources=res)
    assert est.resource_units_budget == pytest.approx(5.0)
    assert est.channels_if_single_family["video"] == 1
