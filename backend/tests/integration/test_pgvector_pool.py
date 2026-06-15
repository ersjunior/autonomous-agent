"""Integração — pool pgvector seguro entre event loops distintos (cenário worker Celery)."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from agents.memory.pgvector_pool import PgVectorPoolHolder, asyncpg_database_url
from tests.db_fixtures import resolve_test_database_url

pytestmark = pytest.mark.integration


async def _count_backend_connections(database_url: str) -> int:
    conn = await asyncpg.connect(asyncpg_database_url(database_url))
    try:
        return int(
            await conn.fetchval(
                """
                SELECT count(*)::int
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                """
            )
        )
    finally:
        await conn.close()


def test_pgvector_pool_recreated_across_event_loops() -> None:
    """Dois asyncio.run() sequenciais simulam tasks Celery com loops diferentes."""
    holder = PgVectorPoolHolder()
    database_url = resolve_test_database_url()

    async def use_pool() -> None:
        pool = await holder.get_pool(database_url)
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT 1") == 1
        await holder.close()

    asyncio.run(use_pool())
    asyncio.run(use_pool())


def test_pgvector_pool_close_releases_postgres_connections() -> None:
    """Fechamento explícito no loop ativo libera conexões (não só descarta referência)."""
    holder = PgVectorPoolHolder()
    database_url = resolve_test_database_url()

    async def use_and_close() -> None:
        before = await _count_backend_connections(database_url)
        pool = await holder.get_pool(database_url)
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT 1") == 1
        during = await _count_backend_connections(database_url)
        assert during >= before
        await holder.close()
        after = await _count_backend_connections(database_url)
        assert after <= before

    asyncio.run(use_and_close())
