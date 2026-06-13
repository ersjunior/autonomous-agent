"""Fixtures de integração — Postgres real, schema via Alembic, isolamento transacional."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import pytest
import pytest_asyncio
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import _async_database_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/autonomous_agent_test"
)


def _sync_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _database_name(url: str) -> str:
    return urlparse(_sync_database_url(url)).path.lstrip("/")


def resolve_test_database_url() -> str:
    """Resolve TEST_DATABASE_URL com proteção contra uso acidental do banco dev/prod."""
    test_url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    test_url = _sync_database_url(test_url)
    test_db = _database_name(test_url)

    if not test_db.endswith("_test"):
        raise RuntimeError(
            f"Banco de teste {test_db!r} deve terminar com '_test' "
            f"(ex.: autonomous_agent_test)."
        )

    prod_url = os.environ.get("DATABASE_URL")
    if prod_url:
        prod_url = _sync_database_url(prod_url)
        prod_db = _database_name(prod_url)
        if test_db == prod_db and not prod_db.endswith("_test"):
            raise RuntimeError(
                f"TEST_DATABASE_URL aponta para o banco de dev/prod ({prod_db!r}). "
                "Use um banco dedicado (ex.: autonomous_agent_test)."
            )

    return test_url


def _ensure_test_database_exists(sync_url: str) -> None:
    db_name = _database_name(sync_url)
    admin_url = sync_url.rsplit("/", 1)[0] + "/postgres"

    conn = psycopg2.connect(admin_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        conn.close()


def _run_alembic_upgrade(sync_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = sync_url
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine():
    """Engine de sessão: extensão vector + Alembic head (sem create_all)."""
    sync_url = resolve_test_database_url()
    _ensure_test_database_exists(sync_url)

    async_url = _async_database_url(sync_url)
    engine = create_async_engine(async_url, poolclass=NullPool)

    async with engine.connect() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.commit()

    _run_alembic_upgrade(sync_url)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """Sessão isolada por transação — rollback garante que nada persiste.

    join_transaction_mode='create_savepoint' permite que código interno chame
    session.commit() sem encerrar a transação externa (savepoint).

    Nota (Etapas 1–9): serviços que fazem commit() fora da Session injetada
    (ex.: abrem sessão própria) ou efeitos colaterais pós-commit exigirão
    begin_nested() explícito ou ajuste nos serviços — não coberto na Etapa 0.
    """
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture(autouse=True)
def clear_tabulacao_codigo_cache():
    """Limpa cache de módulo — IDs de transações rollback não podem vazar entre testes."""
    from app.services import tabulacao_assignment as ta

    ta._codigo_id_cache.clear()
    yield
    ta._codigo_id_cache.clear()
