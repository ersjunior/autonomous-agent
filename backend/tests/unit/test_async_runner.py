"""Unit tests for Celery async runner cleanup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from worker import async_runner
from worker.async_runner import run_celery_async


async def _noop_coro() -> str:
    return "ok"


def test_run_celery_async_delegates_to_cleanup() -> None:
    with patch(
        "worker.async_runner._cleanup_worker_async_resources",
        new_callable=AsyncMock,
    ) as cleanup:
        result = run_celery_async(_noop_coro())

    assert result == "ok"
    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_worker_async_resources_invokes_all_steps() -> None:
    dispose_engine = AsyncMock()
    with (
        patch(
            "agents.memory.pgvector_pool.dispose_pgvector_pools",
            new_callable=AsyncMock,
        ) as dispose_pg,
        patch(
            "agents.orchestrator.graph.reset_worker_async_clients",
            new_callable=AsyncMock,
        ) as reset_redis,
        patch("app.core.database.engine") as engine_mock,
    ):
        engine_mock.dispose = dispose_engine
        await async_runner._cleanup_worker_async_resources()

    dispose_pg.assert_awaited_once()
    reset_redis.assert_awaited_once()
    dispose_engine.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_continues_after_pgvector_failure() -> None:
    dispose_engine = AsyncMock()
    with (
        patch(
            "agents.memory.pgvector_pool.dispose_pgvector_pools",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pgvector fail"),
        ),
        patch(
            "agents.orchestrator.graph.reset_worker_async_clients",
            new_callable=AsyncMock,
        ) as reset_redis,
        patch("app.core.database.engine") as engine_mock,
    ):
        engine_mock.dispose = dispose_engine
        await async_runner._cleanup_worker_async_resources()

    reset_redis.assert_awaited_once()
    dispose_engine.assert_awaited_once()
