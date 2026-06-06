"""Testes unitários — mapeamento intent/status/SIP → tabulação."""

from __future__ import annotations

import pytest

from app.services import tabulacao_mapping as tm

pytestmark = pytest.mark.unit


class TestResolveTabulacaoByRules:
    def test_purchase_maps_to_venda(self) -> None:
        assert tm.resolve_tabulacao_by_rules("purchase", None) == "NEG:VENDA"

    def test_cancel_maps_to_recusado(self) -> None:
        assert tm.resolve_tabulacao_by_rules("cancel", None) == "NEG:RECUSADO"

    def test_escalate_maps_to_escalado(self) -> None:
        assert tm.resolve_tabulacao_by_rules("escalate", None) == "NEG:ESCALADO"

    def test_nao_atendido_status_maps_to_ausente(self) -> None:
        assert tm.resolve_tabulacao_by_rules(None, "nao_atendido") == "NEG:AUSENTE"

    def test_unknown_intent_returns_none(self) -> None:
        assert tm.resolve_tabulacao_by_rules("greeting", None) is None
        assert tm.resolve_tabulacao_by_rules("question", "em_andamento") is None

    def test_intent_takes_precedence_over_status(self) -> None:
        assert tm.resolve_tabulacao_by_rules("purchase", "nao_atendido") == "NEG:VENDA"

    def test_case_insensitive(self) -> None:
        assert tm.resolve_tabulacao_by_rules("PURCHASE", None) == "NEG:VENDA"
        assert tm.resolve_tabulacao_by_rules(None, "NAO_ATENDIDO") == "NEG:AUSENTE"


class TestSipNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("486", "SIP:486"),
            ("SIP:486", "SIP:486"),
            ("sip:480", "SIP:480"),
            ("200", "SIP:200"),
        ],
    )
    def test_valid_codes(self, raw: str, expected: str) -> None:
        assert tm.normalize_sip_code(raw) == expected
        assert tm.resolve_tabulacao_by_sip(raw) == expected

    @pytest.mark.parametrize("raw", ["", "999", "SIP:999", "ABC", "  "])
    def test_invalid_codes_return_none(self, raw: str) -> None:
        assert tm.normalize_sip_code(raw) is None
        assert tm.resolve_tabulacao_by_sip(raw) is None


class TestEscalationTabulacao:
    def test_resolve_tabulacao_for_escalation(self) -> None:
        assert tm.resolve_tabulacao_for_escalation() == "NEG:ESCALADO"


class TestStatusFromTabulacao:
    @pytest.mark.parametrize(
        ("codigo", "expected"),
        [
            ("NEG:SUCESSO", "convertido"),
            ("NEG:VENDA", "convertido"),
            ("NEG:RECUSADO", "recusou"),
            ("NEG:ABANDONO", "nao_atendido"),
            ("NEG:AUSENTE", "nao_atendido"),
        ],
    )
    def test_known_codes(self, codigo: str, expected: str) -> None:
        assert tm.status_from_tabulacao_codigo(codigo) == expected

    def test_unknown_code_falls_back_to_nao_atendido(self) -> None:
        assert tm.status_from_tabulacao_codigo("NEG:DESCONHECIDO") == "nao_atendido"
        assert tm.status_from_tabulacao_codigo("") == "nao_atendido"
