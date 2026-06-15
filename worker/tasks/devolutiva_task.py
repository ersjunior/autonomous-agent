"""Tarefa agendada para geração diária de devolutivas."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.lead_base import LeadBase
from app.services.devolutiva import DEVOLUTIVAS_ROOT, gerar_devolutiva_base
from worker.async_runner import run_celery_async
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _gerar_devolutivas_diarias_async() -> int:
    today = date.today()
    processed = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(LeadBase).where(
                or_(LeadBase.data_fim.is_(None), LeadBase.data_fim >= today),
            )
        )
        lead_bases = list(result.scalars().all())

        for lead_base in lead_bases:
            xlsx_bytes = await gerar_devolutiva_base(session, lead_base.id)
            output_dir = DEVOLUTIVAS_ROOT / str(lead_base.id)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{today.isoformat()}.xlsx"
            output_path.write_bytes(xlsx_bytes)
            processed += 1
            logger.info("Devolutiva gerada: %s", output_path)

    logger.info("Devolutivas diárias concluídas: %s base(s) processada(s)", processed)
    return processed


@celery.task(name="worker.tasks.devolutiva_task.gerar_devolutivas_diarias")
def gerar_devolutivas_diarias() -> int:
    """Gera arquivos xlsx de devolutiva para todas as bases ativas."""
    return run_celery_async(_gerar_devolutivas_diarias_async())
