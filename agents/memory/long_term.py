"""Long-term memory (PostgreSQL + pgvector)."""

import uuid
from datetime import datetime, timezone

import asyncpg
from pgvector.asyncpg import register_vector

from agents.provider_factory import ProviderFactory
from app.core.config import settings


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
        llm = ProviderFactory.get_llm()
        return await llm.embed(text)

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
    ) -> list[dict]:
        top_k = settings.rag_top_k if limit is None else limit
        if top_k <= 0:
            return []

        threshold = settings.rag_similarity_threshold
        fetch_limit = top_k * 3 if threshold > 0 else top_k

        query_embedding = await self._embed(query)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, message, response, intent, created_at,
                       (1 - (embedding <=> $2)) AS similarity
                FROM interactions
                WHERE user_id = $1
                ORDER BY embedding <=> $2
                LIMIT $3
                """,
                user_id,
                query_embedding,
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
                    "similarity": similarity,
                }
            )
            if len(results) >= top_k:
                break

        return results
