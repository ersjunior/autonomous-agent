"""Testes — parse tolerante de JSON do Ollama (_parse_json_content + fallback)."""

import json

import pytest
from pydantic import BaseModel, Field

from agents.providers.llm.ollama_provider import OllamaLLMProvider
from agents.workers.intent_agent import IntentResult


class _SampleSchema(BaseModel):
    value: str = Field(default="ok")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"intent": "greeting", "confidence": 0.9, "entities": {}}', "greeting"),
        (
            'Aqui está o resultado:\n{"intent": "question", "confidence": 0.8, "entities": {}}\nFim.',
            "question",
        ),
        (
            '```json\n{"intent": "purchase", "confidence": 0.7, "entities": {"produto": "X"}}\n```',
            "purchase",
        ),
        (
            '{"intent": "other", "confidence": 0.5, "entities": {}, "complaint_severity": "low"}',
            "other",
        ),
    ],
)
def test_parse_json_content_valid_inputs(raw: str, expected: str) -> None:
    parsed = OllamaLLMProvider._parse_json_content(raw)
    assert parsed is not None
    assert parsed["intent"] == expected


@pytest.mark.parametrize(
    "raw",
    [
        '{"intent": "question", "confidence": 0.4, "entities": {',
        "Olá, não tenho JSON aqui.",
        "",
        "   ",
        "```json\n{\"intent\": \"question\"",
    ],
)
def test_coerce_structured_output_fallback_without_exception(raw: str) -> None:
    result = OllamaLLMProvider()._coerce_structured_output(raw, IntentResult)
    assert isinstance(result, IntentResult)
    assert result.intent == "question"
    assert result.confidence == 0.5
    assert result.entities == {}
    assert result.complaint_severity == "low"


def test_parse_json_content_truncated_returns_none() -> None:
    assert OllamaLLMProvider._parse_json_content('{"intent": "question"') is None


def test_parse_json_content_plain_text_returns_none() -> None:
    assert OllamaLLMProvider._parse_json_content("resposta sem json") is None


def test_coerce_structured_output_valid_json_unchanged() -> None:
    raw = json.dumps(
        {
            "intent": "greeting",
            "confidence": 0.95,
            "entities": {"nome": "Ana"},
            "complaint_severity": "low",
        }
    )
    result = OllamaLLMProvider()._coerce_structured_output(raw, IntentResult)
    assert result.intent == "greeting"
    assert result.confidence == 0.95
    assert result.entities == {"nome": "Ana"}


def test_extract_json_object_ignores_outer_prose() -> None:
    raw = 'Prefixo {"intent": "cancel", "confidence": 0.6, "entities": {}} sufixo'
    extracted = OllamaLLMProvider._extract_json_object(raw)
    assert extracted is not None
    data = json.loads(extracted)
    assert data["intent"] == "cancel"


def test_structured_fallback_unknown_schema() -> None:
    fallback = OllamaLLMProvider._structured_fallback(_SampleSchema)
    assert isinstance(fallback, _SampleSchema)
    assert fallback.value == "ok"
