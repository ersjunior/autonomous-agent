"""Integração — KB retrieval: similaridade pgvector, escopo, status, threshold."""

from __future__ import annotations

import pytest

from agents.tools.knowledge_base import KnowledgeBaseRetriever
from app.models.knowledge import KBDocumentStatus
from tests.integration.helpers import OwnerContext, seed_kb_document_with_chunks, unit_vector

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_system_doc_ordering_by_similarity(
    db_session, pgvector_conn, owner_ctx: OwnerContext
):
    """Doc READY is_system + 2 chunks (e0, e1); query e0 → e0 primeiro."""
    retriever = KnowledgeBaseRetriever()
    e0, e1 = unit_vector(0), unit_vector(1)
    await seed_kb_document_with_chunks(
        db_session,
        pgvector_conn,
        user_id=owner_ctx.user.id,
        owner_user_id=owner_ctx.user.id,
        is_system=True,
        status=KBDocumentStatus.READY.value,
        chunks=[("chunk e0", e0), ("chunk e1", e1)],
    )

    results = await retriever.get_similar(
        owner_ctx.user.id,
        "query",
        query_embedding=e0,
        threshold=0.0,
        conn=pgvector_conn,
    )

    assert len(results) >= 2
    assert results[0]["content"] == "chunk e0"
    assert results[0]["similarity"] > results[1]["similarity"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [KBDocumentStatus.PROCESSING.value, KBDocumentStatus.ERROR.value])
async def test_non_ready_doc_excluded(
    db_session, pgvector_conn, owner_ctx: OwnerContext, status: str
):
    """Doc PROCESSING/ERROR → excluído pelo JOIN status=READY."""
    retriever = KnowledgeBaseRetriever()
    e0 = unit_vector(0)
    await seed_kb_document_with_chunks(
        db_session,
        pgvector_conn,
        user_id=owner_ctx.user.id,
        owner_user_id=owner_ctx.user.id,
        is_system=True,
        status=status,
        chunks=[("hidden chunk", e0)],
    )

    results = await retriever.get_similar(
        owner_ctx.user.id,
        "query",
        query_embedding=e0,
        conn=pgvector_conn,
    )

    assert results == []


@pytest.mark.asyncio
async def test_private_doc_owner_scope(
    db_session, pgvector_conn, owner_ctx: OwnerContext, second_owner
):
    """Doc privado (is_system=False, owner=A) → visível só para owner A."""
    retriever = KnowledgeBaseRetriever()
    e0 = unit_vector(0)
    await seed_kb_document_with_chunks(
        db_session,
        pgvector_conn,
        user_id=owner_ctx.user.id,
        owner_user_id=owner_ctx.user.id,
        is_system=False,
        status=KBDocumentStatus.READY.value,
        chunks=[("private chunk", e0)],
        title="Private doc",
    )

    for owner, expect_visible in [
        (owner_ctx.user.id, True),
        (second_owner.id, False),
        (None, False),
    ]:
        results = await retriever.get_similar(
            owner,
            "query",
            query_embedding=e0,
            conn=pgvector_conn,
        )
        if expect_visible:
            assert any(r["content"] == "private chunk" for r in results)
        else:
            assert not any(r["content"] == "private chunk" for r in results)


@pytest.mark.asyncio
async def test_institutional_doc_visible_to_all_owners(
    db_session, pgvector_conn, owner_ctx: OwnerContext, second_owner
):
    """Doc institucional (is_system=True) → visível para None, A e B."""
    retriever = KnowledgeBaseRetriever()
    e0 = unit_vector(0)
    await seed_kb_document_with_chunks(
        db_session,
        pgvector_conn,
        user_id=owner_ctx.user.id,
        owner_user_id=owner_ctx.user.id,
        is_system=True,
        status=KBDocumentStatus.READY.value,
        chunks=[("institutional chunk", e0)],
        title="Institutional doc",
    )

    for owner in (None, owner_ctx.user.id, second_owner.id):
        results = await retriever.get_similar(
            owner,
            "query",
            query_embedding=e0,
            conn=pgvector_conn,
        )
        assert any(r["content"] == "institutional chunk" for r in results)


@pytest.mark.asyncio
async def test_threshold_filters_orthogonal_chunk(
    db_session, pgvector_conn, owner_ctx: OwnerContext
):
    """Chunk ortogonal (e1) + threshold alto → filtrado."""
    retriever = KnowledgeBaseRetriever()
    e0, e1 = unit_vector(0), unit_vector(1)
    await seed_kb_document_with_chunks(
        db_session,
        pgvector_conn,
        user_id=owner_ctx.user.id,
        owner_user_id=owner_ctx.user.id,
        is_system=True,
        status=KBDocumentStatus.READY.value,
        chunks=[("match e0", e0), ("orthogonal e1", e1)],
    )

    results = await retriever.get_similar(
        owner_ctx.user.id,
        "query",
        query_embedding=e0,
        threshold=0.99,
        conn=pgvector_conn,
    )

    contents = [r["content"] for r in results]
    assert "match e0" in contents
    assert "orthogonal e1" not in contents


@pytest.mark.asyncio
async def test_top_k_respects_limit_and_order(
    db_session, pgvector_conn, owner_ctx: OwnerContext
):
    """3 chunks → ordem por distância crescente, respeita limite."""
    retriever = KnowledgeBaseRetriever()
    e0, e1, e2 = unit_vector(0), unit_vector(1), unit_vector(2)
    await seed_kb_document_with_chunks(
        db_session,
        pgvector_conn,
        user_id=owner_ctx.user.id,
        owner_user_id=owner_ctx.user.id,
        is_system=True,
        status=KBDocumentStatus.READY.value,
        chunks=[
            ("chunk e0", e0),
            ("chunk e1", e1),
            ("chunk e2", e2),
        ],
    )

    results = await retriever.get_similar(
        owner_ctx.user.id,
        "query",
        limit=2,
        threshold=0.0,
        query_embedding=e0,
        conn=pgvector_conn,
    )

    assert len(results) == 2
    assert results[0]["content"] == "chunk e0"
    assert results[0]["similarity"] >= results[1]["similarity"]
