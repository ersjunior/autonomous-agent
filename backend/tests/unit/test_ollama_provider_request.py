"""Testes — payload unificado Ollama (modelo, keep_alive, num_ctx)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.providers.llm.ollama_provider import OllamaLLMProvider
from agents.workers.intent_agent import IntentResult
from app.core.config import settings


@pytest.mark.asyncio
async def test_complete_uses_unified_model_keep_alive_and_num_ctx(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_model", "llama3.2")
    monkeypatch.setattr(settings, "ollama_keep_alive", -1)
    monkeypatch.setattr(settings, "ollama_num_ctx", 4096)

    provider = OllamaLLMProvider()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "ok"}}
    provider._client = AsyncMock()
    provider._client.post = AsyncMock(return_value=mock_response)

    await provider.complete(
        [{"role": "user", "content": "oi"}],
        temperature=0.2,
        max_tokens=112,
    )

    provider._client.post.assert_awaited_once()
    call_kwargs = provider._client.post.await_args
    assert call_kwargs.args[0] == "/api/chat"
    body = call_kwargs.kwargs["json"]
    assert body["model"] == "llama3.2"
    assert body["keep_alive"] == -1
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["num_predict"] == 112
    assert body["options"]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_complete_structured_uses_same_model_as_generation(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_model", "llama3.2")
    monkeypatch.setattr(settings, "ollama_keep_alive", -1)
    monkeypatch.setattr(settings, "ollama_num_ctx", 4096)

    provider = OllamaLLMProvider()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "content": '{"intent": "question", "confidence": 0.9, "entities": {}, "complaint_severity": "low"}'
        }
    }
    provider._client = AsyncMock()
    provider._client.post = AsyncMock(return_value=mock_response)

    result = await provider.complete(
        [{"role": "user", "content": "preço?"}],
        temperature=0.3,
        structured_output_schema=IntentResult,
        max_tokens=128,
    )

    assert isinstance(result, IntentResult)
    body = provider._client.post.await_args.kwargs["json"]
    assert body["model"] == "llama3.2"
    assert body["keep_alive"] == -1
    assert body["options"]["num_ctx"] == 4096
    assert body["format"] == "json"


@pytest.mark.asyncio
async def test_embed_uses_embed_model_with_keep_alive(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_embed_model", "nomic-embed-text")
    monkeypatch.setattr(settings, "ollama_keep_alive", -1)

    provider = OllamaLLMProvider()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1, 0.2]}
    provider._client = AsyncMock()
    provider._client.post = AsyncMock(return_value=mock_response)

    vec = await provider.embed("consulta")

    assert vec == [0.1, 0.2]
    body = provider._client.post.await_args.kwargs["json"]
    assert body["model"] == "nomic-embed-text"
    assert body["keep_alive"] == -1
