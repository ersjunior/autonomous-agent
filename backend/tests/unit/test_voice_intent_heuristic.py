"""Testes unitários — heurística de intent para canal voice."""

from __future__ import annotations

import pytest

from agents.escalation import resolve_should_escalate
from agents.workers.voice_intent_heuristic import (
    apply_voice_first_turn_intent,
    identify_intent_voice_heuristic,
)

pytestmark = pytest.mark.unit


class TestVoiceIntentHeuristic:
    def test_escalate_human_request(self) -> None:
        result = identify_intent_voice_heuristic("Quero falar com um atendente humano")
        assert result.intent == "escalate"
        assert resolve_should_escalate(result.intent, result.confidence, result.complaint_severity)

    def test_purchase_signal(self) -> None:
        result = identify_intent_voice_heuristic("Aceito, pode mandar o contrato")
        assert result.intent == "purchase"

    def test_cancel_signal(self) -> None:
        result = identify_intent_voice_heuristic("Não tenho interesse, pare de ligar")
        assert result.intent == "cancel"

    def test_complaint_high_severity(self) -> None:
        result = identify_intent_voice_heuristic("Isso é um absurdo, vou no Procon")
        assert result.intent == "complaint"
        assert result.complaint_severity == "high"
        assert resolve_should_escalate(result.intent, result.confidence, result.complaint_severity)

    def test_default_question_no_escalation(self) -> None:
        result = identify_intent_voice_heuristic("Qual o horário de funcionamento?")
        assert result.intent == "question"
        assert result.confidence >= 0.25
        assert resolve_should_escalate(result.intent, result.confidence, result.complaint_severity) is False

    def test_greeting_short(self) -> None:
        result = identify_intent_voice_heuristic("Olá, bom dia")
        assert result.intent == "greeting"

    def test_schedule_agendar(self) -> None:
        result = identify_intent_voice_heuristic("Quero agendar uma reunião")
        assert result.intent == "schedule"
        assert result.confidence >= 0.85

    def test_schedule_marcar_horario(self) -> None:
        result = identify_intent_voice_heuristic("Posso marcar um horário para visita?")
        assert result.intent == "schedule"

    def test_schedule_remarcar(self) -> None:
        result = identify_intent_voice_heuristic("Preciso remarcar minha visita")
        assert result.intent == "schedule"

    def test_question_horario_funcionamento_not_schedule(self) -> None:
        result = identify_intent_voice_heuristic("Qual o horário de funcionamento?")
        assert result.intent == "question"
        assert result.intent != "schedule"

    @pytest.mark.parametrize(
        "message",
        [
            "tem outro horario",
            "queria ver outro dia",
            "tem outra data",
            "ver outros horarios",
            "outra agenda",
            "outro horario por favor",
            "tem um novo horario",
        ],
    )
    def test_schedule_follow_up_after_booking(self, message: str) -> None:
        result = identify_intent_voice_heuristic(message)
        assert result.intent == "schedule"

    @pytest.mark.parametrize(
        "message",
        [
            "qual o endereco?",
            "quanto custa?",
            "como funciona o produto?",
            "ate outro dia, obrigado",
        ],
    )
    def test_non_schedule_stays_question(self, message: str) -> None:
        result = identify_intent_voice_heuristic(message)
        assert result.intent == "question"

    @pytest.mark.parametrize(
        "message",
        [
            "tchau",
            "era so isso",
            "pode desligar",
            "nao preciso de mais nada",
            "nao, era so isso",
        ],
    )
    def test_farewell_intent(self, message: str) -> None:
        result = identify_intent_voice_heuristic(message)
        assert result.intent == "farewell"
        assert result.confidence >= 0.9

    def test_first_turn_reclassifies_farewell_to_greeting(self) -> None:
        raw = identify_intent_voice_heuristic("Tchau, tchau.")
        adjusted, opening = apply_voice_first_turn_intent(raw, conversation_history=[])
        assert opening is True
        assert adjusted.intent == "greeting"

    def test_first_turn_keeps_farewell_when_history_exists(self) -> None:
        raw = identify_intent_voice_heuristic("tchau")
        adjusted, opening = apply_voice_first_turn_intent(
            raw,
            conversation_history=[{"role": "user", "content": "oi"}],
        )
        assert opening is False
        assert adjusted.intent == "farewell"

    def test_bare_nao_is_not_farewell(self) -> None:
        result = identify_intent_voice_heuristic("não")
        assert result.intent == "question"

    def test_bare_obrigado_is_not_farewell(self) -> None:
        result = identify_intent_voice_heuristic("obrigado")
        assert result.intent == "question"

    def test_schedule_follow_up_not_farewell(self) -> None:
        result = identify_intent_voice_heuristic("tem outro horario")
        assert result.intent == "schedule"
        assert result.intent != "farewell"
