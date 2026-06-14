"""Testes unitários — decisão de escalonamento (B-1)."""

from __future__ import annotations

import pytest

from agents.escalation import (
    ESCALATION_CONFIDENCE_THRESHOLD,
    resolve_should_escalate,
)

pytestmark = pytest.mark.unit


class TestResolveShouldEscalate:
    def test_explicit_escalate_intent(self) -> None:
        assert resolve_should_escalate("escalate", 1.0, "low") is True

    def test_low_confidence_escalates(self) -> None:
        assert (
            resolve_should_escalate("other", ESCALATION_CONFIDENCE_THRESHOLD - 0.01, "low")
            is True
        )

    def test_confidence_0_2_escalates(self) -> None:
        """Abaixo do limiar (0.25) — escala por incerteza extrema."""
        assert resolve_should_escalate("question", 0.2, "low") is True

    def test_confidence_0_4_does_not_escalate(self) -> None:
        """Acima do limiar antigo (0.5) mas abaixo de certeza — bot responde."""
        assert resolve_should_escalate("other", 0.4, "low") is False

    def test_confidence_at_threshold_does_not_escalate(self) -> None:
        assert resolve_should_escalate("other", ESCALATION_CONFIDENCE_THRESHOLD, "low") is False

    def test_high_confidence_normal_conversation(self) -> None:
        assert resolve_should_escalate("question", 0.95, "low") is False

    def test_complaint_low_severity_does_not_escalate(self) -> None:
        assert resolve_should_escalate("complaint", 0.9, "low") is False

    def test_complaint_high_severity_escalates(self) -> None:
        assert resolve_should_escalate("complaint", 0.9, "high") is True

    def test_complaint_high_severity_case_insensitive(self) -> None:
        assert resolve_should_escalate("complaint", 0.9, "HIGH") is True

    def test_empty_complaint_severity_treated_as_low(self) -> None:
        assert resolve_should_escalate("complaint", 0.9, "") is False
