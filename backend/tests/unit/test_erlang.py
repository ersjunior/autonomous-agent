"""Testes unitários — Erlang B/C e dimensionamento (R-C)."""

from __future__ import annotations

import math

import pytest

from app.core import erlang

# Referência validada em backend/scripts/validate_layer_rc_capacity.py
REF_A = 10.0
REF_N = 14
REF_AHT = 180.0
REF_T = 20.0
REF_SL_EXPECTED = 0.8725
REF_SL_TOLERANCE = 0.002


@pytest.mark.unit
class TestErlangReference:
    """Caso de referência A=10, N=14 — prova que a fórmula está correta."""

    def test_erlang_c_reference(self) -> None:
        pw = erlang.erlang_c(REF_A, REF_N)
        assert 0.0 < pw < 1.0

    def test_service_level_reference(self) -> None:
        sl = erlang.service_level(REF_N, REF_A, REF_T, REF_AHT)
        assert sl == pytest.approx(REF_SL_EXPECTED, abs=REF_SL_TOLERANCE)

    def test_required_agents_meets_target_sl(self) -> None:
        n_req = erlang.required_agents(REF_A, 0.80, REF_T, REF_AHT)
        sl_at_n = erlang.service_level(n_req, REF_A, REF_T, REF_AHT)
        assert sl_at_n >= 0.80
        assert n_req >= math.ceil(REF_A)


@pytest.mark.unit
class TestErlangB:
    def test_zero_traffic_returns_zero(self) -> None:
        assert erlang.erlang_b(0.0, 10) == 0.0
        assert erlang.erlang_b(-1.0, 10) == 0.0

    def test_zero_agents_returns_zero(self) -> None:
        assert erlang.erlang_b(5.0, 0) == 0.0

    def test_traffic_at_or_above_agents_is_full_blocking(self) -> None:
        assert erlang.erlang_b(10.0, 10) == 1.0
        assert erlang.erlang_b(15.0, 10) == 1.0

    def test_stable_system_has_partial_blocking(self) -> None:
        b = erlang.erlang_b(5.0, 10)
        assert 0.0 < b < 1.0


@pytest.mark.unit
class TestErlangC:
    def test_zero_traffic_returns_zero(self) -> None:
        assert erlang.erlang_c(0.0, 10) == 0.0

    def test_unstable_system_returns_one(self) -> None:
        """A >= N: sistema instável — Pw documentado como 1.0."""
        assert erlang.erlang_c(REF_A, REF_N - 4) == 1.0  # A=10, N=10
        assert erlang.erlang_c(12.0, 10) == 1.0

    def test_stable_system_probability_between_zero_and_one(self) -> None:
        pw = erlang.erlang_c(REF_A, REF_N)
        assert 0.0 < pw < 1.0


@pytest.mark.unit
class TestServiceLevel:
    def test_zero_traffic_is_perfect_sl(self) -> None:
        assert erlang.service_level(5, 0.0, REF_T, REF_AHT) == 1.0

    def test_invalid_inputs_return_zero(self) -> None:
        assert erlang.service_level(0, REF_A, REF_T, REF_AHT) == 0.0
        assert erlang.service_level(REF_N, REF_A, REF_T, 0.0) == 0.0
        assert erlang.service_level(REF_N, REF_A, -1.0, REF_AHT) == 0.0

    def test_unstable_system_sl_is_zero(self) -> None:
        sl = erlang.service_level(10, 10.0, REF_T, REF_AHT)
        assert sl == 0.0

    def test_result_is_clamped_to_unit_interval(self) -> None:
        sl = erlang.service_level(REF_N, REF_A, REF_T, REF_AHT)
        assert 0.0 <= sl <= 1.0


@pytest.mark.unit
class TestRequiredAgents:
    def test_zero_traffic_returns_one(self) -> None:
        assert erlang.required_agents(0.0, 0.80, REF_T, REF_AHT) == 1

    def test_higher_traffic_needs_more_agents(self) -> None:
        n_low = erlang.required_agents(5.0, 0.80, REF_T, REF_AHT)
        n_high = erlang.required_agents(REF_A, 0.80, REF_T, REF_AHT)
        assert n_high >= n_low

    def test_higher_target_sl_needs_more_agents(self) -> None:
        n_80 = erlang.required_agents(REF_A, 0.80, REF_T, REF_AHT)
        n_95 = erlang.required_agents(REF_A, 0.95, REF_T, REF_AHT)
        assert n_95 >= n_80

    def test_invalid_aht_falls_back_to_ceil_traffic(self) -> None:
        assert erlang.required_agents(REF_A, 0.80, REF_T, 0.0) == math.ceil(REF_A)


@pytest.mark.unit
class TestTrafficIntensity:
    def test_lambda_and_aht_to_erlangs(self) -> None:
        # 360 contatos/h × 180s AHT = 360 × (180/3600) = 18 Erlangs
        a = erlang.traffic_intensity_erlangs(360.0, 180.0)
        assert a == pytest.approx(18.0)

    def test_zero_inputs_return_zero(self) -> None:
        assert erlang.traffic_intensity_erlangs(0.0, 180.0) == 0.0
        assert erlang.traffic_intensity_erlangs(100.0, 0.0) == 0.0

    def test_large_values_remain_finite(self) -> None:
        a = erlang.traffic_intensity_erlangs(10_000.0, 300.0)
        assert math.isfinite(a)
        sl = erlang.service_level(200, a, 20.0, 300.0)
        assert math.isfinite(sl)
        assert 0.0 <= sl <= 1.0
