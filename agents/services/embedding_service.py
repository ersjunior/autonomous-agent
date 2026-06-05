"""Shared text embedding helper (memória de longo prazo + KB)."""

from __future__ import annotations

from agents.provider_factory import ProviderFactory


async def embed_text(text: str) -> list[float]:
    """Gera embedding denso via ProviderFactory (nomic-embed-text / OpenAI)."""
    llm = ProviderFactory.get_llm()
    return await llm.embed(text)
