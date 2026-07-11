"""Unit tests for voice-specific RAG routing in the orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.orchestrator.graph import _fetch_rag_context
from agents.workers.response_agent import build_response_messages, format_rag_context_block


@pytest.mark.asyncio
async def test_voice_rag_skips_conversation_history_but_keeps_kb():
    """Voice: sem memória de conversas passadas; KB do projeto continua."""
    state = {
        "message": "horario de atendimento",
        "channel": "voice",
        "user_id": "+5511999999999",
        "owner_user_id": "a3448f9b-4c81-4b11-b056-698f7c887c8e",
    }
    fake_embedding = [0.1] * 8

    with (
        patch("agents.orchestrator.graph.embed_text", new_callable=AsyncMock) as embed_mock,
        patch("agents.orchestrator.graph._long_term_memory") as memory_mock,
        patch("agents.orchestrator.graph._kb_retriever") as kb_mock,
        patch("agents.orchestrator.graph.settings") as settings_mock,
    ):
        settings_mock.voice_kb_similarity_threshold = 0.50
        embed_mock.return_value = fake_embedding
        memory_mock.retrieve_similar_memories = AsyncMock(return_value=[{"message": "old"}])
        kb_mock.retrieve_kb_chunks = AsyncMock(return_value=[{"content": "kb"}])

        memories, chunks, rag_ms = await _fetch_rag_context(state)

        embed_mock.assert_awaited_once_with("horario de atendimento")
        memory_mock.retrieve_similar_memories.assert_not_awaited()
        kb_mock.retrieve_kb_chunks.assert_awaited_once_with(
            "a3448f9b-4c81-4b11-b056-698f7c887c8e",
            "horario de atendimento",
            top_k=None,
            threshold=0.50,
            query_embedding=fake_embedding,
        )
        assert memories == []
        assert chunks == [{"content": "kb"}]
        assert rag_ms >= 0


@pytest.mark.asyncio
async def test_whatsapp_rag_uses_global_defaults_not_voice_overrides():
    """WhatsApp: memória de conversas + KB (comportamento inalterado)."""
    state = {
        "message": "qual o preco do curso",
        "channel": "whatsapp",
        "user_id": "+5511888888888",
        "owner_user_id": "owner-uuid",
    }

    with (
        patch("agents.orchestrator.graph.embed_text", new_callable=AsyncMock) as embed_mock,
        patch("agents.orchestrator.graph._long_term_memory") as memory_mock,
        patch("agents.orchestrator.graph._kb_retriever") as kb_mock,
    ):
        embed_mock.return_value = [0.2] * 8
        memory_mock.retrieve_similar_memories = AsyncMock(return_value=[])
        kb_mock.retrieve_kb_chunks = AsyncMock(return_value=[])

        await _fetch_rag_context(state)

        memory_mock.retrieve_similar_memories.assert_awaited_once_with(
            "+5511888888888",
            "qual o preco do curso",
            limit=None,
            threshold=None,
            query_embedding=[0.2] * 8,
        )
        kb_mock.retrieve_kb_chunks.assert_awaited_once_with(
            "owner-uuid",
            "qual o preco do curso",
            top_k=None,
            threshold=None,
            query_embedding=[0.2] * 8,
        )


def test_voice_messages_exclude_past_conversation_rag_even_if_passed():
    """Defesa em profundidade: bloco de conversas passadas não entra no prompt de voz."""
    past = [{"message": "Olá", "response": "Olá novamente!", "similarity": 0.94}]
    kb = [{"content": "Cursos de IA e tecnologia.", "document_title": "Catálogo"}]

    messages = build_response_messages(
        "quais cursos vocês têm?",
        "question",
        {},
        [],
        "voice",
        rag_memories=past,
        kb_chunks=kb,
    )

    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert format_rag_context_block(past) is not None
    assert "Conversas anteriores relevantes" not in system_text
    assert "Cursos de IA e tecnologia" in system_text
