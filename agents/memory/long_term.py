"""Long-term memory (PostgreSQL + pgvector).

pgvector cosine distance (operador ``<=>``):
  - 0 = vetores idênticos, 2 = direções opostas (vetores normalizados).
  - Similaridade usada no RAG: ``similarity = 1 - distance`` (ver SQL em ``get_similar``).
  - ``rag_similarity_threshold``: mantém linhas com ``similarity >= threshold``
    (equivalente a ``distance <= 1 - threshold``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

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


class LongTermMemory:
    """Persists and retrieves agent interactions with semantic search."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                _asyncpg_database_url(settings.database_url),
                init=_init_connection,
            )
        return self._pool

    async def _embed(self, text: str) -> list[float]:
        return await embed_text(text)

    async def save_interaction(
        self,
        user_id: str,
        message: str,
        response: str,
        intent: str,
    ) -> None:
        embedding = await self._embed(f"{message}\n{response}")
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO interactions (
                    id, user_id, message, response, intent, embedding, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid.uuid4(),
                user_id,
                message,
                response,
                intent,
                embedding,
                datetime.now(timezone.utc),
            )

    async def get_similar(
        self,
        user_id: str,
        query: str,
        limit: int | None = None,
        *,
        query_embedding: list[float] | None = None,
    ) -> list[dict]:
        """Busca interações passadas do mesmo ``user_id`` por similaridade semântica.

        Args:
            user_id: Identificador do contato (isolamento obrigatório entre clientes).
            query: Texto da mensagem atual (embedding gerado se ``query_embedding`` omitido).
            query_embedding: Vetor pré-calculado da query (evita segundo embed na mesma volta).
        """
        top_k = settings.rag_top_k if limit is None else limit
        if top_k <= 0:
            return []

        threshold = settings.rag_similarity_threshold
        fetch_limit = top_k * 3 if threshold > 0 else top_k

        embedding = query_embedding if query_embedding is not None else await self._embed(query)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, message, response, intent, created_at,
                       (embedding <=> $2) AS distance,
                       (1 - (embedding <=> $2)) AS similarity
                FROM interactions
                WHERE user_id = $1
                ORDER BY embedding <=> $2
                LIMIT $3
                """,
                user_id,
                embedding,
                fetch_limit,
            )

        results: list[dict] = []
        for row in rows:
            similarity = float(row["similarity"])
            if threshold > 0 and similarity < threshold:
                continue
            results.append(
                {
                    "id": str(row["id"]),
                    "user_id": row["user_id"],
                    "message": row["message"],
                    "response": row["response"],
                    "intent": row["intent"],
                    "created_at": row["created_at"].isoformat(),
                    "distance": float(row["distance"]),
                    "similarity": similarity,
                }
            )
            if len(results) >= top_k:
                break

        return results

    async def retrieve_similar_memories(self, user_id: str, query: str) -> list[dict]:
        """Recuperação RAG com degradação graciosa (retorna [] se embed/busca falhar)."""
        if not (query or "").strip():
            return []
        try:
            memories = await self.get_similar(user_id, query)
            if memories:
                logger.info(
                    "RAG: %s memória(s) para user_id=%s (top_k=%s, threshold=%s)",
                    len(memories),
                    user_id,
                    settings.rag_top_k,
                    settings.rag_similarity_threshold,
                )
            return memories
        except Exception:
            logger.warning(
                "RAG retrieval failed for user_id=%s; continuing without long-term context",
                user_id,
                exc_info=True,
            )
            return []
