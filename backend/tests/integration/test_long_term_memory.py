"""Integração — long-term memory: similaridade pgvector, isolamento, threshold."""

from __future__ import annotations

import pytest

from agents.memory.long_term import LongTermMemory
from tests.integration.helpers import seed_interaction_with_embedding, unit_vector

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ordering_by_similarity(db_session, pgvector_conn):
    """3 interactions do user A (e0,e1,e2); query e0 → e0 primeiro."""
    memory = LongTermMemory()
    user_a = "user-a-sim"
    e0, e1, e2 = unit_vector(0), unit_vector(1), unit_vector(2)
    await seed_interaction_with_embedding(
        pgvector_conn, user_id=user_a, message="m0", response="r0", embedding=e0
    )
    await seed_interaction_with_embedding(
        pgvector_conn, user_id=user_a, message="m1", response="r1", embedding=e1
    )
    await seed_interaction_with_embedding(
        pgvector_conn, user_id=user_a, message="m2", response="r2", embedding=e2
    )

    results = await memory.get_similar(
        user_a,
        "query",
        query_embedding=e0,
        conn=pgvector_conn,
    )

    assert len(results) >= 3
    assert results[0]["message"] == "m0"
    assert results[0]["similarity"] >= results[1]["similarity"]


@pytest.mark.asyncio
async def test_user_id_isolation(db_session, pgvector_conn):
    """User B com mesmo embedding → get_similar(A) não retorna os de B."""
    memory = LongTermMemory()
    e0 = unit_vector(0)
    await seed_interaction_with_embedding(
        pgvector_conn, user_id="user-a", message="secret-a", response="r", embedding=e0
    )
    await seed_interaction_with_embedding(
        pgvector_conn, user_id="user-b", message="secret-b", response="r", embedding=e0
    )

    results = await memory.get_similar(
        "user-a",
        "query",
        query_embedding=e0,
        conn=pgvector_conn,
    )

    messages = [r["message"] for r in results]
    assert "secret-a" in messages
    assert "secret-b" not in messages


@pytest.mark.asyncio
async def test_save_and_retrieve_same_connection(pgvector_conn, monkeypatch):
    """save_interaction + get_similar na mesma conn → round-trip visível."""
    memory = LongTermMemory()
    e0 = unit_vector(0)
    user_id = "round-trip-user"

    async def fake_embed(_text: str) -> list[float]:
        return e0

    monkeypatch.setattr("agents.memory.long_term.embed_text", fake_embed)

    await memory.save_interaction(
        user_id,
        "client msg",
        "agent reply",
        "question",
        conn=pgvector_conn,
    )

    results = await memory.get_similar(
        user_id,
        "query",
        query_embedding=e0,
        conn=pgvector_conn,
    )

    assert len(results) == 1
    assert results[0]["message"] == "client msg"
    assert results[0]["response"] == "agent reply"


@pytest.mark.asyncio
async def test_threshold_filters_low_similarity(db_session, pgvector_conn, monkeypatch):
    """rag_similarity_threshold alto vs 0.0 → comportamento distinto."""
    memory = LongTermMemory()
    user_id = "threshold-user"
    e0, e1 = unit_vector(0), unit_vector(1)
    await seed_interaction_with_embedding(
        pgvector_conn, user_id=user_id, message="close", response="r", embedding=e0
    )
    await seed_interaction_with_embedding(
        pgvector_conn, user_id=user_id, message="far", response="r", embedding=e1
    )

    monkeypatch.setattr("agents.memory.long_term.settings.rag_similarity_threshold", 0.99)
    high = await memory.get_similar(
        user_id, "query", query_embedding=e0, conn=pgvector_conn
    )
    messages_high = {r["message"] for r in high}
    assert "close" in messages_high
    assert "far" not in messages_high

    monkeypatch.setattr("agents.memory.long_term.settings.rag_similarity_threshold", 0.0)
    low = await memory.get_similar(
        user_id, "query", query_embedding=e0, conn=pgvector_conn
    )
    messages_low = {r["message"] for r in low}
    assert "close" in messages_low
    assert "far" in messages_low


@pytest.mark.asyncio
async def test_query_embedding_skips_embed(db_session, pgvector_conn, monkeypatch):
    """query_embedding passado → embed_text NÃO é chamado."""
    memory = LongTermMemory()
    e0 = unit_vector(0)
    await seed_interaction_with_embedding(
        pgvector_conn, user_id="embed-skip", message="m", response="r", embedding=e0
    )

    calls: list[str] = []

    async def tracking_embed(text: str) -> list[float]:
        calls.append(text)
        return e0

    monkeypatch.setattr("agents.memory.long_term.embed_text", tracking_embed)

    await memory.get_similar(
        "embed-skip",
        "should not embed",
        query_embedding=e0,
        conn=pgvector_conn,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_retrieve_similar_memories_graceful_on_error(monkeypatch):
    """Exceção simulada → retrieve_similar_memories retorna []."""
    memory = LongTermMemory()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(memory, "get_similar", boom)

    result = await memory.retrieve_similar_memories("any-user", "any query")

    assert result == []
