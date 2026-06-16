"""Unit tests for KB RAG diagnostic logging."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.knowledge_base import KnowledgeBaseRetriever


@pytest.mark.asyncio
async def test_retrieve_kb_chunks_logs_best_sim_when_empty(caplog):
    caplog.set_level(logging.INFO, logger="agents.tools.knowledge_base")
    retriever = KnowledgeBaseRetriever()
    peek_chunk = [{"similarity": 0.602, "content": "x", "document_title": "Doc"}]

    with patch.object(
        retriever,
        "get_similar",
        new_callable=AsyncMock,
        side_effect=[[], peek_chunk],
    ):
        with patch("agents.tools.knowledge_base.settings") as settings_mock:
            settings_mock.resolved_kb_top_k.return_value = 7
            settings_mock.kb_similarity_threshold = 0.62
            result = await retriever.retrieve_kb_chunks(
                "owner-id",
                "horario de atendimento",
                threshold=0.50,
            )

    assert result == []
    assert "KB RAG: 0 chunks (best_sim=0.602)" in caplog.text
