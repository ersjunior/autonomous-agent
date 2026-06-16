"""Unit tests for voice-specific RAG routing in the orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.orchestrator.graph import _fetch_rag_context


@pytest.mark.asyncio
async def test_voice_rag_separates_memory_limit_from_kb_top_k_and_thresholds():
    """Voice: memória limitada; KB usa top_k global e threshold de voz."""
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
        settings_mock.voice_rag_top_k = 3
        settings_mock.voice_rag_similarity_threshold = 0.5
        settings_mock.voice_kb_similarity_threshold = 0.50
        embed_mock.return_value = fake_embedding
        memory_mock.retrieve_similar_memories = AsyncMock(return_value=[])
        kb_mock.retrieve_kb_chunks = AsyncMock(return_value=[{"content": "kb"}])

        memories, chunks, rag_ms = await _fetch_rag_context(state)

        embed_mock.assert_awaited_once_with("horario de atendimento")
        memory_mock.retrieve_similar_memories.assert_awaited_once_with(
            "+5511999999999",
            "horario de atendimento",
            limit=3,
            threshold=0.5,
            query_embedding=fake_embedding,
        )
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
    """WhatsApp: sem limit/threshold de voz."""
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
