"""Tarefa agendada para marcar leads acionados sem resposta como nao_atendido."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.lead_interaction import LeadInteraction
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _marcar_nao_atendidos_async() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.status_timeout_hours)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(LeadInteraction)
            .where(
                LeadInteraction.status == "acionado",
                LeadInteraction.data_acionamento.isnot(None),
                LeadInteraction.data_acionamento < cutoff,
                or_(
                    LeadInteraction.data_ultimo_contato == LeadInteraction.data_acionamento,
                    and_(
                        LeadInteraction.data_ultimo_contato.is_(None),
                        LeadInteraction.data_acionamento.isnot(None),
                    ),
                ),
            )
            .values(status="nao_atendido")
        )
        updated = result.rowcount or 0
        await session.commit()

    logger.info(
        "Status sweep: %s lead_interaction(s) marcada(s) como nao_atendido (timeout=%sh)",
        updated,
        settings.status_timeout_hours,
    )
    return updated


@celery.task(name="worker.tasks.status_sweep.marcar_nao_atendidos")
def marcar_nao_atendidos() -> int:
    """Marca interações acionadas sem resposta após STATUS_TIMEOUT_HOURS."""
    return asyncio.run(_marcar_nao_atendidos_async())
