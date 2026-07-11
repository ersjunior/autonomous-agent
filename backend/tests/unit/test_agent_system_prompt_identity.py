"""Unit tests — ancoragem de persona no agent_system_prompt e identity rules."""

from __future__ import annotations

import pytest

from agents.identity import format_institutional_identity_block
from app.core.config import DEFAULT_AGENT_SYSTEM_PROMPT

pytestmark = pytest.mark.unit


def test_default_prompt_has_firm_identity_anchor() -> None:
    prompt = DEFAULT_AGENT_SYSTEM_PROMPT.lower()
    assert "nunca revele" in prompt
    assert "meta" in prompt
    assert "assistente virtual" in prompt
    assert "dados de treinamento" in prompt


def test_default_prompt_removed_ia_escape_clause() -> None:
    prompt = DEFAULT_AGENT_SYSTEM_PROMPT.lower()
    assert "a menos que o cliente pergunte diretamente" not in prompt
    assert "a menos que o cliente pergunte" not in prompt


def test_default_prompt_keeps_anti_hallucination_rules() -> None:
    prompt = DEFAULT_AGENT_SYSTEM_PROMPT
    assert "NUNCA invente" in prompt
    assert "base de conhecimento" in prompt
    assert "não possui essa informação" in prompt


def test_identity_rules_reinforce_no_base_model_leak() -> None:
    block = format_institutional_identity_block(
        {"identity": {"company_name": "ByteCell", "display_name": "ByteCell Academy"}}
    )
    assert block is not None
    assert "você É o assistente virtual desta empresa" in block
    assert "NUNCA revele" in block
    assert "Meta" in block
    assert "NÃO invente preços" in block
