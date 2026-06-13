"""Pool asyncpg compartilhado para retrievers pgvector (memória + KB)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import asyncpg
from pgvector.asyncpg import register_vector


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
    )


class PgVectorPoolHolder:
    """Lazy pool asyncpg com codec vector registrado no init."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def get_pool(self, database_url: str) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await create_pgvector_pool(database_url)
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
