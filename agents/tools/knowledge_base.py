"""Knowledge base retrieval (KB-2) — RAG institucional complementar à memória de contato.

Escopo da busca:
  - Chunks de documentos ``is_system=True`` (institucionais, visíveis a todos).
  - Chunks cujo ``owner_user_id`` coincide com o dono do agente/campanha.
  - Apenas documentos com ``status=READY``.

Quando ``owner_user_id`` é None (ex.: contato sem dono resolvido), a busca ainda
retorna chunks institucionais (``is_system``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from agents.services.embedding_service import embed_text
from app.core.config import settings

logger = logging.getLogger(__name__)


def _asyncpg_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


class KnowledgeBaseRetriever:
    """Busca semântica em kb_chunks com join em kb_documents para escopo e status."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                _asyncpg_database_url(settings.database_url),
                init=_init_connection,
            )
        return self._pool

    @staticmethod
    def _parse_owner(owner_user_id: str | uuid.UUID | None) -> uuid.UUID | None:
        if owner_user_id is None:
            return None
        if isinstance(owner_user_id, uuid.UUID):
            return owner_user_id
        raw = str(owner_user_id).strip()
        if not raw:
            return None
        return uuid.UUID(raw)

    async def get_similar(
        self,
        owner_user_id: str | uuid.UUID | None,
        query: str,
        limit: int | None = None,
        *,
        threshold: float | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca chunks por similaridade cosseno (padrão de ``LongTermMemory.get_similar``)."""
        top_k = settings.resolved_kb_top_k() if limit is None else limit
        if top_k <= 0:
            return []

        sim_threshold = (
            settings.kb_similarity_threshold if threshold is None else threshold
        )
        fetch_limit = top_k * 3 if sim_threshold > 0 else top_k

        owner_uuid = self._parse_owner(owner_user_id)
        embedding = (
            query_embedding if query_embedding is not None else await embed_text(query)
        )

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.document_id, c.owner_user_id, c.chunk_index, c.content,
                       c.created_at,
                       d.title AS document_title, d.is_system AS document_is_system,
                       (c.embedding <=> $2) AS distance,
                       (1 - (c.embedding <=> $2)) AS similarity
                FROM kb_chunks c
                INNER JOIN kb_documents d ON d.id = c.document_id
                WHERE d.status = 'READY'
                  AND (
                    d.is_system = TRUE
                    OR ($1::uuid IS NOT NULL AND c.owner_user_id = $1::uuid)
                  )
                ORDER BY c.embedding <=> $2
                LIMIT $3
                """,
                owner_uuid,
                embedding,
                fetch_limit,
            )

        results: list[dict[str, Any]] = []
        for row in rows:
            similarity = float(row["similarity"])
            if sim_threshold > 0 and similarity < sim_threshold:
                continue
            results.append(
                {
                    "id": str(row["id"]),
                    "document_id": str(row["document_id"]),
                    "document_title": row["document_title"],
                    "document_is_system": bool(row["document_is_system"]),
                    "owner_user_id": str(row["owner_user_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "content": row["content"],
                    "created_at": row["created_at"].isoformat(),
                    "distance": float(row["distance"]),
                    "similarity": similarity,
                }
            )
            if len(results) >= top_k:
                break

        return results

    async def retrieve_kb_chunks(
        self,
        owner_user_id: str | uuid.UUID | None,
        query: str,
        *,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Recuperação RAG KB com degradação graciosa (retorna [] se embed/busca falhar)."""
        if not (query or "").strip():
            return []
        try:
            chunks = await self.get_similar(
                owner_user_id,
                query,
                limit=top_k,
                threshold=threshold,
            )
            if chunks:
                logger.info(
                    "KB RAG: %s chunk(s) para owner_user_id=%s (top_k=%s, threshold=%s)",
                    len(chunks),
                    owner_user_id,
                    top_k or settings.kb_top_k,
                    threshold if threshold is not None else settings.kb_similarity_threshold,
                )
                for item in chunks:
                    logger.debug(
                        "KB chunk sim=%.3f title=%r is_system=%s | %s",
                        item.get("similarity", 0),
                        item.get("document_title"),
                        item.get("document_is_system"),
                        (item.get("content") or "")[:120],
                    )
            return chunks
        except Exception:
            logger.warning(
                "KB retrieval failed for owner_user_id=%s; continuing without KB context",
                owner_user_id,
                exc_info=True,
            )
            return []


_retriever = KnowledgeBaseRetriever()


async def retrieve_kb_chunks(
    owner_user_id: str | uuid.UUID | None,
    query: str,
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Atalho de módulo — espelha ``retrieve_similar_memories`` da memória de longo prazo."""
    return await _retriever.retrieve_kb_chunks(
        owner_user_id,
        query,
        top_k=top_k,
        threshold=threshold,
    )
