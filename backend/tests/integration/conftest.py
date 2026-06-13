"""Fixtures de integração — Postgres real, schema via Alembic, isolamento transacional."""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import date, datetime, timezone
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
from app.core.security import hash_password
from app.core.seed import seed_default_admin, seed_default_tabulacoes
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
from app.models.lead_interaction import LeadInteraction
from app.models.user import User
from pgvector.asyncpg import register_vector
import redis

from app.core.config import settings
from tests.integration.helpers import OwnerContext, create_owner_context

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/autonomous_agent_test"
)

# Padrões Redis usados por handoff, capacidade, slots e settings_version (sem rollback).
REDIS_CLEANUP_PATTERNS = (
    "human_mode:*",
    "human_mode_notified:*",
    "global_capacity_holder:*",
    "outbound_capacity:*",
    "contact_capacity:*",
    "lead_capacity_user:*",
    "slots_set:*",
    "slot_holder:*",
    "priority_queue:*",
    "lead_slot:*",
    "campaign_inflight:*",
)
REDIS_CLEANUP_KEYS = (
    "settings_version",
    "global_capacity_usage",
    "global_capacity_holders",
)


def flush_redis_test_keys() -> None:
    """Remove chaves de teste — Postgres faz rollback, Redis não."""
    client = redis.from_url(settings.redis_url, decode_responses=True)
    for key in REDIS_CLEANUP_KEYS:
        client.delete(key)
    for pattern in REDIS_CLEANUP_PATTERNS:
        for key in client.scan_iter(pattern, count=500):
            client.delete(key)


@pytest.fixture
def clean_redis():
    """Isola Redis entre testes de integração (before + after)."""
    flush_redis_test_keys()
    yield
    flush_redis_test_keys()


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


@pytest_asyncio.fixture
async def pgvector_conn(db_session):
    """asyncpg.Connection da mesma transação que db_session (rollback isola)."""
    sa_conn = await db_session.connection()
    raw = await sa_conn.get_raw_connection()
    asyncpg_conn = raw.driver_connection
    await register_vector(asyncpg_conn)
    yield asyncpg_conn


@pytest.fixture(autouse=True)
def clear_tabulacao_codigo_cache():
    """Limpa cache de módulo — IDs de transações rollback não podem vazar entre testes."""
    from app.services import tabulacao_assignment as ta

    ta._codigo_id_cache.clear()
    yield
    ta._codigo_id_cache.clear()


# --- Factories compartilhadas (Etapas 1+) ---


@pytest_asyncio.fixture
async def seeded_catalog(db_session):
    """Admin + catálogo system NEG:* / SIP:* (seed idempotente)."""
    await seed_default_admin(db_session)
    await seed_default_tabulacoes(db_session)
    return db_session


@pytest_asyncio.fixture
async def owner_ctx(seeded_catalog, db_session) -> OwnerContext:
    return await create_owner_context(db_session)


@pytest_asyncio.fixture
async def second_owner(db_session) -> User:
    """Segundo usuário para testes de isolamento entre donos."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"other-{suffix}@example.com",
        hashed_password=hash_password("secret"),
        full_name="Other Owner",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def system_seeds(db_session):
    """Admin + seeds completos (channels, agents, tabulações, flags)."""
    from app.core.seed import (
        ensure_seed_flags,
        seed_default_admin,
        seed_default_agents,
        seed_default_channels,
        seed_default_tabulacoes,
    )

    await seed_default_admin(db_session)
    await seed_default_channels(db_session)
    await seed_default_agents(db_session)
    await seed_default_tabulacoes(db_session)
    await ensure_seed_flags(db_session)
    return db_session


@pytest_asyncio.fixture
async def lead_interaction(owner_ctx: OwnerContext, db_session) -> LeadInteraction:
    """LI pré-existente em em_andamento (útil para tabulação)."""
    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        tentativas=1,
        data_acionamento=datetime.now(timezone.utc),
    )
    db_session.add(li)
    await db_session.flush()
    await db_session.refresh(li, attribute_names=["campaign_id"])
    li.campaign = owner_ctx.campaign
    return li


@pytest.fixture
def mock_classify(monkeypatch):
    """Mock de classify_tabulacao (LLM) — state['return_value'] controla o código."""
    state: dict = {"return_value": "NEG:NUM_ERRADO", "calls": []}

    async def fake_classify(text: str, catalog: list[dict[str, str]]) -> str | None:
        state["calls"].append(
            {
                "text": text,
                "catalog_codigos": [row["codigo"] for row in catalog],
            }
        )
        return state["return_value"]

    monkeypatch.setattr(
        "app.services.tabulacao_assignment.classify_tabulacao",
        fake_classify,
    )
    return state


@pytest.fixture
def mock_capacity_release(monkeypatch):
    """Mock das liberações Redis ao atingir status terminal (upsert_lead_interaction)."""
    state: dict = {
        "slot_calls": [],
        "outbound_calls": [],
        "receptive_calls": [],
    }

    def fake_release_slot(lead_id: str, channel: str) -> bool:
        state["slot_calls"].append((lead_id, channel))
        return True

    def fake_release_outbound(lead_id: str, channel: str) -> bool:
        state["outbound_calls"].append((lead_id, channel))
        return True

    def fake_release_receptive(lead_id: str, channel: str) -> bool:
        state["receptive_calls"].append((lead_id, channel))
        return True

    monkeypatch.setattr(
        "app.services.activation_slots.release_slot_for_lead",
        fake_release_slot,
    )
    monkeypatch.setattr(
        "app.services.capacity_service.release_outbound_capacity_for_lead",
        fake_release_outbound,
    )
    monkeypatch.setattr(
        "app.services.capacity_service.release_receptive_capacity_for_lead",
        fake_release_receptive,
    )
    monkeypatch.setattr(
        "app.services.activation_history.release_slot_for_lead",
        fake_release_slot,
    )
    monkeypatch.setattr(
        "app.services.activation_history.release_outbound_capacity_for_lead",
        fake_release_outbound,
    )
    return state
