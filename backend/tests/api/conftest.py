"""Fixtures da Camada 3 — HTTP via AsyncClient + overrides de dependências."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def test_app(db_session: AsyncSession):
    """App FastAPI com get_db apontando para a sessão transacional de teste."""
    from app.core.database import get_db
    from app.main import app

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    # httpx 0.28 não expõe lifespan="off" no ASGITransport — noop evita migrations/seed.
    app.router.lifespan_context = noop_lifespan

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        # Mesma instância da fixture — sem close(); rollback fica no teardown de db_session.
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan


@pytest_asyncio.fixture
async def client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP in-process — schema já migrado pela fixture test_engine (Camada 2)."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(test_app, client: AsyncClient, owner_ctx) -> AsyncClient:
    """Cliente autenticado via override de get_current_user (sem JWT)."""
    from app.core.security import get_current_user

    async def override_get_current_user():
        return owner_ctx.user

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    yield client
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def other_auth_client(test_app, client: AsyncClient, second_owner) -> AsyncClient:
    """Cliente autenticado como segundo dono (isolamento entre usuários)."""
    from app.core.security import get_current_user

    async def override_get_current_user():
        return second_owner

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    yield client
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def auth_headers(owner_ctx) -> dict[str, str]:
    """JWT real do owner — para testes que exercitam decode + lookup no DB."""
    from app.core.security import create_access_token

    token = create_access_token(
        data={"sub": str(owner_ctx.user.id), "email": owner_ctx.user.email},
    )
    return {"Authorization": f"Bearer {token}"}
