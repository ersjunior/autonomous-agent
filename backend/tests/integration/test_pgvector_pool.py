"""Integração — pool pgvector seguro entre event loops distintos (cenário worker Celery)."""

from __future__ import annotations

import asyncio

import pytest

from agents.memory.pgvector_pool import PgVectorPoolHolder
from tests.db_fixtures import resolve_test_database_url

pytestmark = pytest.mark.integration


def test_pgvector_pool_recreated_across_event_loops() -> None:
    """Dois asyncio.run() sequenciais simulam tasks Celery com loops diferentes."""
    holder = PgVectorPoolHolder()
    database_url = resolve_test_database_url()

    async def use_pool() -> None:
        pool = await holder.get_pool(database_url)
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT 1") == 1

    asyncio.run(use_pool())
    asyncio.run(use_pool())
