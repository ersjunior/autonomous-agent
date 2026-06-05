"""Tarefa agendada para marcar leads acionados sem resposta como nao_atendido."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.lead_interaction import LeadInteraction
from app.services.tabulacao_assignment import maybe_apply_tabulacao_on_transition
from worker.celery_app import celery

logger = logging.getLogger(__name__)


def _no_response_filter(cutoff: datetime):
    return and_(
        LeadInteraction.status == "acionado",
        LeadInteraction.data_acionamento.isnot(None),
        LeadInteraction.data_acionamento < cutoff,
        or_(
            LeadInteraction.data_ultimo_contato.is_(None),
            LeadInteraction.data_ultima_tentativa.is_(None),
            LeadInteraction.data_ultimo_contato <= LeadInteraction.data_ultima_tentativa,
            and_(
                LeadInteraction.data_ultima_tentativa.is_(None),
                or_(
                    LeadInteraction.data_ultimo_contato == LeadInteraction.data_acionamento,
                    LeadInteraction.data_ultimo_contato.is_(None),
                ),
            ),
        ),
    )


async def _marcar_nao_atendidos_async() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.status_timeout_hours)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LeadInteraction).where(_no_response_filter(cutoff))
        )
        records = list(result.scalars().all())
        updated = 0
        for record in records:
            record.status = "nao_atendido"
            await maybe_apply_tabulacao_on_transition(
                session,
                record,
                status_interno="nao_atendido",
                channel=record.channel_type,
                conversation_text=record.devolutiva,
            )
            updated += 1
        if updated:
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
