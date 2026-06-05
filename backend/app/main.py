"""FastAPI application entrypoint."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.seed import (
    ensure_seed_flags,
    seed_default_admin,
    seed_default_agents,
    seed_default_channels,
    seed_default_tabulacoes,
)
from app.services.settings_sync import bootstrap_settings

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_migrations() -> None:
    """Aplica as migrations Alembic até o head (fonte única do schema)."""
    cfg = AlembicConfig(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    await asyncio.to_thread(_run_migrations)

    async with AsyncSessionLocal() as db:
        await seed_default_admin(db)
        await seed_default_channels(db)
        await seed_default_agents(db)
        await seed_default_tabulacoes(db)
        await ensure_seed_flags(db)

    await bootstrap_settings()

    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "healthy", "service": settings.app_name}
