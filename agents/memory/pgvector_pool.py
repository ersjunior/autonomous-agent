"""Pool asyncpg compartilhado para retrievers pgvector (memória + KB)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import asyncpg
from pgvector.asyncpg import register_vector

logger = logging.getLogger(__name__)


def asyncpg_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


async def init_pgvector_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def create_pgvector_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        asyncpg_database_url(database_url),
        init=init_pgvector_connection,
        min_size=1,
        max_size=3,
    )


class PgVectorPoolHolder:
    """Lazy pool asyncpg com codec vector registrado no init.

    No worker Celery cada task usa ``asyncio.run`` (loop novo). O pool asyncpg fica ligado
    ao loop em que foi criado; reutilizá-lo em outro loop causa
    "Future attached to a different loop". Por isso associamos o pool ao ``id(loop)`` atual.
    """

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._loop_id: int | None = None

    async def close(self) -> None:
        """Close the pool on the **active** event loop (releases TCP connections in Postgres)."""
        if self._pool is None:
            return
        try:
            await self._pool.close()
        except Exception:
            logger.warning("PgVector pool close failed; discarding reference", exc_info=True)
        self._pool = None
        self._loop_id = None

    async def _discard_stale_pool(self) -> None:
        # Loop from a prior asyncio.run() is already dead — cannot close remotely.
        if self._pool is not None:
            logger.debug(
                "PgVector pool from previous event loop discarded without close "
                "(loop already closed; rely on run_celery_async cleanup before loop exit)"
            )
        self._pool = None
        self._loop_id = None

    async def get_pool(self, database_url: str) -> asyncpg.Pool:
        loop = asyncio.get_running_loop()
        current_loop_id = id(loop)

        if self._pool is not None and self._loop_id != current_loop_id:
            await self._discard_stale_pool()

        if self._pool is None:
            self._pool = await create_pgvector_pool(database_url)
            self._loop_id = current_loop_id

        return self._pool


@asynccontextmanager
async def use_pgvector_connection(
    get_pool: Callable[[], Awaitable[asyncpg.Pool]],
    conn: asyncpg.Connection | None = None,
) -> AsyncIterator[asyncpg.Connection]:
    """Usa conexão injetada (teste) ou acquire do pool (produção)."""
    if conn is not None:
        yield conn
    else:
        pool = await get_pool()
        async with pool.acquire() as acquired:
            yield acquired


async def dispose_pgvector_pools() -> None:
    """Close asyncpg pools held by graph/KB singletons (call inside active Celery task loop)."""
    from agents.orchestrator.graph import close_long_term_pgvector_pool
    from agents.tools.knowledge_base import close_kb_pgvector_pool

    await close_long_term_pgvector_pool()
    await close_kb_pgvector_pool()
