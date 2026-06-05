"""
Métricas agregadas da fila receptiva (R-B) — consulta QueueEntry + Redis.

Definições:
  - total_atendidos: ANSWERED no período (inclui imediatos com wait_seconds=0).
  - total_enfileirados: passaram pela fila (wait_seconds > 0, ou ainda WAITING, ou ABANDONED).
    Atendimentos imediatos (wait=0) não entram no denominador de abandono.
  - total_abandonados: ABANDONED no período (só voz; em mensageria tende a 0).
  - tempo_medio_espera: média de wait_seconds dos ANSWERED com wait_seconds > 0.
  - taxa_abandono: abandonados / enfileirados (0 se enfileirados=0).
  - nivel_servico: % dos ANSWERED com wait_seconds <= service_level_target_seconds
    (imediatos contam como atendidos em 0s).
  - tamanho_fila_atual: soma queue_size Redis por canal messaging.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activation_defaults import MESSAGING_CHANNELS, SUPPORTED_CHANNEL_TYPES
from app.core.config import settings
from app.models.queue_entry import QueueEntry, QueueEntryStatus
from app.schemas.metrics import ChannelQueueMetrics, QueueMetricsResponse
from app.services.receptive_queue import queue_size


def _period_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(1, days))


def _is_enqueued_metric(entry: QueueEntry) -> bool:
    """Passou pela fila (exclui atendimento imediato wait=0)."""
    if entry.status == QueueEntryStatus.WAITING:
        return True
    if entry.status == QueueEntryStatus.ABANDONED:
        return True
    if entry.status == QueueEntryStatus.ANSWERED:
        return (entry.wait_seconds or 0) > 0
    return False


async def get_queue_metrics(
    db: AsyncSession,
    *,
    days: int = 1,
) -> QueueMetricsResponse:
    since = _period_start(days)
    target = settings.service_level_target_seconds

    rows = (
        await db.execute(
            select(QueueEntry).where(QueueEntry.enqueued_at >= since)
        )
    ).scalars().all()

    total_atendidos = 0
    total_enfileirados = 0
    total_abandonados = 0
    sum_wait_answered = 0
    count_wait_answered = 0
    sla_met = 0

    by_channel: dict[str, dict] = {}

    for ch in SUPPORTED_CHANNEL_TYPES:
        by_channel[ch] = {
            "total_enfileirados": 0,
            "total_atendidos": 0,
            "total_abandonados": 0,
            "sum_wait": 0,
            "count_wait": 0,
            "sla_met": 0,
            "answered_count_sla": 0,
        }

    for entry in rows:
        ch = entry.channel_type
        bucket = by_channel.setdefault(
            ch,
            {
                "total_enfileirados": 0,
                "total_atendidos": 0,
                "total_abandonados": 0,
                "sum_wait": 0,
                "count_wait": 0,
                "sla_met": 0,
                "answered_count_sla": 0,
            },
        )

        if entry.status == QueueEntryStatus.ANSWERED:
            total_atendidos += 1
            bucket["total_atendidos"] += 1
            wait = entry.wait_seconds if entry.wait_seconds is not None else 0
            bucket["answered_count_sla"] += 1
            if wait <= target:
                sla_met += 1
                bucket["sla_met"] += 1
            if wait > 0:
                sum_wait_answered += wait
                count_wait_answered += 1
                bucket["sum_wait"] += wait
                bucket["count_wait"] += 1

        if entry.status == QueueEntryStatus.ABANDONED:
            total_abandonados += 1
            bucket["total_abandonados"] += 1

        if _is_enqueued_metric(entry):
            total_enfileirados += 1
            bucket["total_enfileirados"] += 1

    tempo_medio = (
        (sum_wait_answered / count_wait_answered) if count_wait_answered else 0.0
    )
    nivel_servico = (sla_met / total_atendidos) if total_atendidos else 0.0
    taxa_abandono = (
        (total_abandonados / total_enfileirados) if total_enfileirados else 0.0
    )

    tamanho_fila = sum(queue_size(ch) for ch in MESSAGING_CHANNELS)

    por_canal: dict[str, ChannelQueueMetrics] = {}
    for ch, b in by_channel.items():
        answered = b["total_atendidos"]
        por_canal[ch] = ChannelQueueMetrics(
            total_enfileirados=b["total_enfileirados"],
            total_atendidos=answered,
            total_abandonados=b["total_abandonados"],
            tempo_medio_espera=(
                (b["sum_wait"] / b["count_wait"]) if b["count_wait"] else 0.0
            ),
            taxa_abandono=(
                (b["total_abandonados"] / b["total_enfileirados"])
                if b["total_enfileirados"]
                else 0.0
            ),
            nivel_servico=(
                (b["sla_met"] / b["answered_count_sla"]) if b["answered_count_sla"] else 0.0
            ),
            tamanho_fila_atual=queue_size(ch) if ch in MESSAGING_CHANNELS else 0,
        )

    return QueueMetricsResponse(
        period_days=days,
        service_level_target_seconds=target,
        total_enfileirados=total_enfileirados,
        total_atendidos=total_atendidos,
        total_abandonados=total_abandonados,
        tempo_medio_espera=tempo_medio,
        taxa_abandono=taxa_abandono,
        nivel_servico=nivel_servico,
        tamanho_fila_atual=tamanho_fila,
        por_canal=por_canal,
        abandono_apenas_voz=True,
        abandono_disponivel_inbound=False,
    )
