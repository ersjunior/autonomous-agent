"""
Análise de capacidade + Erlang C (R-C) — agrega hardware, uso global, histórico e SLA previsto.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import erlang
from app.core.activation_defaults import MESSAGING_CHANNELS
from app.core.config import settings
from app.models.lead_interaction import LeadInteraction
from app.models.queue_entry import QueueEntry
from app.schemas.capacity import (
    CapacityEstimateSection,
    CapacityResponse,
    CapacityUsageSection,
    ErlangSection,
    ObservedTrafficSection,
    ResourceSection,
)
from app.services.capacity_estimate import (
    channel_costs,
    estimate_capacity,
    read_resources,
    resolve_max_weighted_capacity,
)
from app.services.capacity_service import (
    current_global_usage,
    current_outbound_bound_weight,
    current_receptive_bound_weight,
)
from worker.tasks.conversation_routing import TERMINAL_STATUSES


def _period_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(1, days))


async def _observed_arrival_rate_per_hour(db: AsyncSession, days: int) -> tuple[float, int]:
    """λ ≈ entradas na fila / horas (QueueEntry no período)."""
    since = _period_start(days)
    count = (
        await db.execute(
            select(func.count()).select_from(QueueEntry).where(QueueEntry.enqueued_at >= since)
        )
    ).scalar_one()
    hours = max(days * 24, 1)
    return float(count) / hours, int(count)


async def _observed_aht_seconds(db: AsyncSession, days: int) -> tuple[float, int, str]:
    """
    AHT a partir de LeadInteraction encerradas.

    Proxy: data_acionamento → última atividade (data_ultimo_contato ou
    data_ultima_tentativa). Não inclui wait_seconds da fila (isso é outra métrica).
    Se poucos dados, usa default_aht_seconds configurável.
    """
    since = _period_start(days)
    rows = (
        await db.execute(
            select(LeadInteraction).where(
                LeadInteraction.created_at >= since,
                LeadInteraction.status.in_(tuple(TERMINAL_STATUSES)),
            )
        )
    ).scalars().all()

    durations: list[float] = []
    for row in rows:
        start = row.data_acionamento or row.data_ultima_tentativa or row.created_at
        end = row.data_ultimo_contato or row.data_ultima_tentativa or row.created_at
        if start is None or end is None:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = (end - start).total_seconds()
        if 5 <= delta <= 24 * 3600:
            durations.append(delta)

    if len(durations) >= 3:
        avg = sum(durations) / len(durations)
        return avg, len(durations), "lead_interaction_terminal_span"

    return (
        float(settings.default_aht_seconds),
        len(durations),
        "default_config_insufficient_history",
    )


async def get_capacity_analysis(db: AsyncSession) -> CapacityResponse:
    resources = read_resources()
    estimate = estimate_capacity(resources)
    max_cap = resolve_max_weighted_capacity()
    usage = current_global_usage()
    outbound_w = current_outbound_bound_weight()
    receptive_w = current_receptive_bound_weight()
    unmapped = max(0, usage - outbound_w - receptive_w)

    days = settings.capacity_history_days
    arrival_rate, arrival_count = await _observed_arrival_rate_per_hour(db, days)
    aht_sec, aht_samples, aht_source = await _observed_aht_seconds(db, days)

    traffic_a = erlang.traffic_intensity_erlangs(arrival_rate, aht_sec)
    n_agents = max(1, max_cap)
    target_sec = float(settings.service_level_target_seconds)
    target_sl = float(settings.erlang_target_service_level)

    pw = erlang.erlang_c(traffic_a, n_agents) if traffic_a > 0 else 0.0
    sl_now = erlang.service_level(n_agents, traffic_a, target_sec, aht_sec)
    n_required = erlang.required_agents(traffic_a, target_sl, target_sec, aht_sec)
    sl_at_required = erlang.service_level(n_required, traffic_a, target_sec, aht_sec)

    headroom_agents = max(0, n_agents - n_required)
    headroom_volume_pct = 0.0
    if n_required > 0 and n_agents > n_required:
        headroom_volume_pct = min(100.0, ((n_agents / n_required) - 1.0) * 100.0)

    costs = channel_costs()
    return CapacityResponse(
        resources=ResourceSection(
            cpu_cores=resources.cpu_cores,
            cpu_percent_used=round(resources.cpu_percent_used, 1),
            cpu_available_ratio=round(resources.cpu_available_ratio, 3),
            ram_total_mb=round(resources.ram_total_mb, 1),
            ram_available_mb=round(resources.ram_available_mb, 1),
            gpu_signal_available=resources.gpu_signal_available,
            gpu_signal_source=resources.gpu_signal_source,
            gpu_device_name=resources.gpu_device_name,
            container_estimate=True,
        ),
        estimate=CapacityEstimateSection(
            resource_units_budget=round(estimate.resource_units_budget, 2),
            max_weighted_capacity_estimated=estimate.max_weighted_capacity,
            max_weighted_capacity_effective=max_cap,
            max_weighted_capacity_override=settings.max_weighted_capacity_override,
            channels_if_single_family=estimate.channels_if_single_family,
            channel_costs=costs,
            channel_weights=settings.resolved_channel_weights(),
            notes=estimate.notes,
        ),
        usage=CapacityUsageSection(
            global_usage=usage,
            global_max=max_cap,
            global_remaining=max(0, max_cap - usage),
            outbound_weight_bound=outbound_w,
            receptive_weight_bound=receptive_w,
            unmapped_usage=unmapped,
        ),
        observed=ObservedTrafficSection(
            period_days=days,
            arrival_rate_per_hour=round(arrival_rate, 4),
            arrival_count=arrival_count,
            aht_seconds=round(aht_sec, 1),
            aht_sample_count=aht_samples,
            aht_source=aht_source,
            traffic_intensity_erlangs=round(traffic_a, 4),
        ),
        erlang=ErlangSection(
            num_agents=n_agents,
            traffic_intensity_erlangs=round(traffic_a, 4),
            probability_wait=round(pw, 6),
            service_level_predicted=round(sl_now, 4),
            service_level_target=target_sl,
            service_level_target_seconds=int(target_sec),
            required_agents_for_target=n_required,
            service_level_at_required=round(sl_at_required, 4),
            headroom_agents=headroom_agents,
            headroom_volume_percent=round(headroom_volume_pct, 1),
            analytical_only=True,
        ),
        messaging_channels=sorted(MESSAGING_CHANNELS),
    )
