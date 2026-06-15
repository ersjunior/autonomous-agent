"""Métricas agregadas — fila receptiva (R-B)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.metrics import AgentMetricsResponse, QueueMetricsResponse
from app.services.metrics import get_metrics_by_agent
from app.services.queue_metrics import get_queue_metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/by-agent", response_model=AgentMetricsResponse)
async def metrics_by_agent(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentMetricsResponse:
    """Métricas simples agregadas por agente (comparativo lado a lado)."""
    return await get_metrics_by_agent(db, user_id=user.id)


@router.get("/queue", response_model=QueueMetricsResponse)
async def queue_metrics(
    days: int = Query(1, ge=1, le=90, description="Período em dias (default 24h)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QueueMetricsResponse:
    """Métricas da fila de atendimento receptivo + tamanho atual (Redis)."""
    del user
    return await get_queue_metrics(db, days=days)
