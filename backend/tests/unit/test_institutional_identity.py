"""Unit tests for institutional identity prompt injection (agent.config.identity)."""

from __future__ import annotations

import pytest

from agents.identity import format_institutional_identity_block, non_identity_config
from agents.workers.response_agent import build_response_messages
from app.core.config import DEFAULT_AGENT_SYSTEM_PROMPT, settings

FULL_IDENTITY_CONFIG = {
    "tipo": "inbound",
    "identity": {
        "company_name": "ByteCell",
        "display_name": "ByteCell Educação",
        "tone": "acolhedor, didático, sem jargão",
        "business_context": "Plataforma de cursos online em tecnologia e IA.",
        "greeting_hint": "Cumprimente pelo nome da empresa.",
    },
}


class TestFormatInstitutionalIdentityBlock:
    def test_full_identity(self) -> None:
        block = format_institutional_identity_block(FULL_IDENTITY_CONFIG)
        assert block is not None
        assert "Identidade institucional" in block
        assert "ByteCell Educação" in block
        assert "acolhedor, didático" in block
        assert "Plataforma de cursos online" in block
        assert "Cumprimente pelo nome da empresa" in block
        assert "NÃO invente preços" in block

    def test_display_name_fallback_to_company_name(self) -> None:
        block = format_institutional_identity_block(
            {"identity": {"company_name": "ByteCell"}}
        )
        assert block is not None
        assert "- Empresa: ByteCell" in block
        assert "Tom:" not in block

    def test_partial_fields_only_filled_lines(self) -> None:
        block = format_institutional_identity_block(
            {"identity": {"tone": "formal e objetivo"}}
        )
        assert block is not None
        assert "- Tom: formal e objetivo" in block
        assert "Empresa:" not in block
        assert "Contexto:" not in block

    def test_missing_identity_returns_none(self) -> None:
        assert format_institutional_identity_block({}) is None
        assert format_institutional_identity_block({"tipo": "inbound"}) is None
        assert format_institutional_identity_block(None) is None

    def test_empty_identity_values_returns_none(self) -> None:
        assert format_institutional_identity_block(
            {"identity": {"company_name": "  ", "tone": ""}}
        ) is None

    def test_guardrail_anti_hallucination_present(self) -> None:
        block = format_institutional_identity_block(
            {"identity": {"company_name": "Acme"}}
        )
        assert block is not None
        assert "base de conhecimento abaixo" in block
        assert "NÃO invente preços" in block


class TestNonIdentityConfig:
    def test_strips_identity_key(self) -> None:
        assert non_identity_config(FULL_IDENTITY_CONFIG) == {"tipo": "inbound"}

    def test_empty_when_only_identity(self) -> None:
        assert non_identity_config({"identity": {"company_name": "X"}}) == {}


class TestBuildResponseMessagesIdentityOrder:
    @pytest.fixture(autouse=True)
    def _use_default_system_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Isola ordem de blocos do prompt global (evita override stale em app_settings)."""
        monkeypatch.setattr(settings, "agent_system_prompt", DEFAULT_AGENT_SYSTEM_PROMPT)

    def _system_contents(self, **kwargs) -> list[str]:
        messages = build_response_messages(
            "Olá",
            "greeting",
            {},
            [],
            "telegram",
            **kwargs,
        )
        return [m["content"] for m in messages if m["role"] == "system"]

    def test_with_identity_block_after_global_before_personality(self) -> None:
        contents = self._system_contents(
            agent_config=FULL_IDENTITY_CONFIG,
            agent_personality="Agente: Test (modo RECEPTIVE)",
            agent_mode="RECEPTIVE",
        )
        global_idx = next(i for i, c in enumerate(contents) if DEFAULT_AGENT_SYSTEM_PROMPT[:40] in c)
        identity_idx = next(i for i, c in enumerate(contents) if "Identidade institucional" in c)
        personality_idx = next(
            i for i, c in enumerate(contents) if c.startswith("Agente: Test")
        )
        receptive_idx = next(i for i, c in enumerate(contents) if "Modo RECEPTIVO" in c)

        assert global_idx < identity_idx < personality_idx < receptive_idx

    def test_without_identity_unchanged_no_identity_block(self) -> None:
        contents = self._system_contents(
            agent_config={"tipo": "inbound"},
            agent_personality="Agente: Seed (modo RECEPTIVE)",
            agent_mode="RECEPTIVE",
        )
        assert not any("Identidade institucional" in c for c in contents)
        assert contents[0].startswith("Você é um assistente de atendimento")
        assert contents[1].startswith("Agente: Seed")

    def test_without_agent_config_same_as_empty(self) -> None:
        with_config = self._system_contents(agent_config={"tipo": "inbound"})
        without = self._system_contents()
        assert with_config == without

    def test_personality_excludes_identity_from_operational_config(self) -> None:
        contents = self._system_contents(
            agent_config=FULL_IDENTITY_CONFIG,
            agent_personality=(
                "Agente: X (modo RECEPTIVE)\nConfiguração operacional: {'tipo': 'inbound'}"
            ),
        )
        personality = next(c for c in contents if c.startswith("Agente: X"))
        assert "identity" not in personality
        assert "ByteCell" not in personality
