"""Async database session and engine setup."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


def _async_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _is_worker_process() -> bool:
    """Celery worker children set WORKER_PROCESS=1 (see docker-compose worker service)."""
    return os.environ.get("WORKER_PROCESS", "").strip().lower() in ("1", "true", "yes")


def _create_async_engine():
    url = _async_database_url(settings.database_url)
    if _is_worker_process():
        # One connection per checkout; closed on return — safe across asyncio.run() per task.
        return create_async_engine(url, echo=settings.debug, poolclass=NullPool)
    return create_async_engine(
        url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_recycle=300,
    )


engine = _create_async_engine()
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()