"""Periodic scheduler for active campaign activations (Layers B + C + D)."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.activation_defaults import channel_family, normalize_channel_type
from app.core.activation_window import is_within_window
from app.core.database import AsyncSessionLocal
from app.models.agent_activation import AgentActivation
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.services.activation_cadence import (
    close_lead_no_answer,
    count_recent_dispatches,
    mark_followup_enqueued,
    leads_needing_followup,
    leads_to_close_no_answer,
    remaining_hourly_quota,
    resolve_channel_cadence_params,
)
from app.services.activation_service import (
    get_pending_leads_for_channel,
    resolve_channel_window_params,
)
from app.services.activation_slots import (
    count_active_slots,
    enqueue_priority,
    is_dispatch_inflight,
    mark_dispatch_inflight,
    pop_priority_leads,
    priority_queue_size,
    remove_from_priority,
)
from app.services.capacity_service import (
    OutboundCapacityHandle,
    bind_outbound_capacity,
    try_acquire_outbound_capacity,
)
from worker.async_runner import run_celery_async
from worker.celery_app import celery
from worker.tasks.outbound_campaign import send_campaign_followup, send_campaign_message

logger = logging.getLogger(__name__)

CandidateKind = Literal["priority", "first"]


@dataclass(frozen=True)
class DispatchCandidate:
    lead_id: uuid.UUID
    campaign_id: uuid.UUID
    kind: CandidateKind
    followup: bool = False
    followup_record: LeadInteraction | None = None


def _empty_channel_stats() -> dict:
    return {
        "first_message": 0,
        "followup": 0,
        "closed": 0,
        "skipped_slots": 0,
        "priority_enqueued": 0,
        "priority_dispatched": 0,
        "hourly_quota_used": 0,
        "hourly_quota_limit": 0,
        "hourly_quota_remaining": 0,
        "slots_active": 0,
        "slots_limit": 0,
        "priority_queue_size": 0,
        "campaigns_processed": 0,
        "campaigns_waiting": 0,
    }


def _concurrent_limit(params: dict, channel: str) -> int:
    family = channel_family(channel)
    if family == "voice":
        return int(params.get("chamadas_simultaneas", 1))
    return int(params.get("chats_simultaneos", 5))


def _campaigns_limit(params: dict) -> int:
    return int(params.get("campanhas_simultaneas", 1))


def _enqueue_dispatch(
    candidate: DispatchCandidate,
    channel: str,
    agent_id: uuid.UUID,
    handle: OutboundCapacityHandle,
) -> None:
    aid = str(agent_id)
    lid = str(candidate.lead_id)
    cid = str(candidate.campaign_id)
    bind_outbound_capacity(lid, channel, handle)
    if candidate.followup:
        send_campaign_followup.delay(
            lid, cid, channel, slot_token=handle.slot_token, agent_id=aid
        )
    else:
        send_campaign_message.delay(
            lid, cid, channel, slot_token=handle.slot_token, agent_id=aid
        )


async def _build_candidates_for_activation(
    db,
    activation: AgentActivation,
    channel: str,
    params: dict,
    since_hour: datetime,
) -> list[DispatchCandidate]:
    family = channel_family(channel)
    candidates: list[DispatchCandidate] = []

    if family == "voice":
        limit = int(params.get("tentativas_por_hora", 6))
        recent = await count_recent_dispatches(
            db, activation.campaign_id, channel, since_hour
        )
        quota = remaining_hourly_quota(limit, recent)
        pending = await get_pending_leads_for_channel(
            db, activation.campaign_id, channel
        )
        for lead in pending[:quota]:
            candidates.append(
                DispatchCandidate(
                    lead_id=lead.id,
                    campaign_id=activation.campaign_id,
                    kind="first",
                )
            )
    else:
        minutos = int(params.get("minutos_segunda_mensagem", 20))
        max_tentativas = int(params.get("tentativas_sem_resposta", 2))

        for record in await leads_needing_followup(
            db,
            activation.campaign_id,
            channel,
            minutos,
            max_tentativas,
        ):
            candidates.append(
                DispatchCandidate(
                    lead_id=record.lead_id,
                    campaign_id=activation.campaign_id,
                    kind="first",
                    followup=True,
                    followup_record=record,
                )
            )

        pending = await get_pending_leads_for_channel(
            db, activation.campaign_id, channel
        )
        for lead in pending:
            candidates.append(
                DispatchCandidate(
                    lead_id=lead.id,
                    campaign_id=activation.campaign_id,
                    kind="first",
                )
            )

    return candidates


async def _process_agent_channel_group(
    db,
    agent_id: uuid.UUID,
    channel: str,
    activations: list[AgentActivation],
    since_hour: datetime,
    stats: dict,
) -> None:
    params = await resolve_channel_cadence_params(db, agent_id, channel)
    slot_limit = _concurrent_limit(params, channel)
    camp_limit = _campaigns_limit(params)
    family = channel_family(channel)

    activations_sorted = sorted(
        activations,
        key=lambda a: a.started_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    to_process = activations_sorted[:camp_limit]
    waiting = activations_sorted[camp_limit:]

    aid = str(agent_id)
    slots_before = count_active_slots(aid, channel)
    pq_before = priority_queue_size(aid, channel)

    for act in to_process:
        key = f"{act.campaign_id}:{channel}"
        ch = stats["by_channel"].setdefault(key, _empty_channel_stats())
        ch["campaigns_processed"] = 1
        ch["slots_limit"] = slot_limit
        ch["slots_active"] = slots_before

    for act in waiting:
        key = f"{act.campaign_id}:{channel}"
        ch = stats["by_channel"].setdefault(key, _empty_channel_stats())
        ch["campaigns_waiting"] = 1
        ch["slots_limit"] = slot_limit

    if not to_process:
        return

    priority_popped = pop_priority_leads(aid, channel, max_n=500)
    ordered: list[DispatchCandidate] = []

    for pm in priority_popped:
        ordered.append(
            DispatchCandidate(
                lead_id=uuid.UUID(pm.lead_id),
                campaign_id=uuid.UUID(pm.campaign_id),
                kind="priority",
                followup=pm.is_followup,
            )
        )

    for activation in to_process:
        ordered.extend(
            await _build_candidates_for_activation(
                db, activation, channel, params, since_hour
            )
        )

    free_slots = max(0, slot_limit - count_active_slots(aid, channel))
    now_score = time.time()

    followup_marked = False

    for candidate in ordered:
        key = f"{candidate.campaign_id}:{channel}"
        ch_stats = stats["by_channel"].setdefault(key, _empty_channel_stats())
        ch_stats["slots_limit"] = slot_limit
        ch_stats["priority_queue_size"] = pq_before

        cid = str(candidate.campaign_id)
        lid = str(candidate.lead_id)
        if is_dispatch_inflight(cid, lid, channel):
            continue

        if free_slots <= 0:
            enqueue_priority(aid, channel, cid, lid, score=now_score, followup=candidate.followup)
            ch_stats["skipped_slots"] += 1
            ch_stats["priority_enqueued"] += 1
            stats["priority_enqueued"] = stats.get("priority_enqueued", 0) + 1
            continue

        handle = try_acquire_outbound_capacity(aid, channel, params)
        if handle is None:
            enqueue_priority(aid, channel, cid, lid, score=now_score, followup=candidate.followup)
            ch_stats["skipped_slots"] += 1
            ch_stats["priority_enqueued"] += 1
            stats["priority_enqueued"] = stats.get("priority_enqueued", 0) + 1
            continue

        if candidate.followup and candidate.followup_record is not None:
            await mark_followup_enqueued(db, candidate.followup_record)
            followup_marked = True

        mark_dispatch_inflight(cid, lid, channel)
        _enqueue_dispatch(candidate, channel, agent_id, handle)
        free_slots -= 1
        ch_stats["slots_active"] = count_active_slots(aid, channel)

        if candidate.kind == "priority":
            ch_stats["priority_dispatched"] += 1
            stats["priority_dispatched"] = stats.get("priority_dispatched", 0) + 1
        elif candidate.followup:
            ch_stats["followup"] += 1
            stats["followups_enqueued"] += 1
        else:
            ch_stats["first_message"] += 1
            stats["leads_enqueued"] += 1

        remove_from_priority(
            aid,
            channel,
            str(candidate.campaign_id),
            str(candidate.lead_id),
            followup=candidate.followup,
        )

    if followup_marked:
        await db.commit()

    if family == "messaging":
        for activation in to_process:
            minutos = int(params.get("minutos_segunda_mensagem", 20))
            max_tentativas = int(params.get("tentativas_sem_resposta", 2))
            key = f"{activation.campaign_id}:{channel}"
            ch_stats = stats["by_channel"].setdefault(key, _empty_channel_stats())

            for record in await leads_to_close_no_answer(
                db,
                activation.campaign_id,
                channel,
                minutos,
                max_tentativas,
            ):
                await close_lead_no_answer(db, record)
                ch_stats["closed"] += 1
                stats["leads_closed"] += 1

    if any(
        stats["by_channel"].get(f"{a.campaign_id}:{channel}", {}).get("followup")
        for a in to_process
    ) or stats.get("leads_closed"):
        await db.commit()

    for activation in to_process:
        key = f"{activation.campaign_id}:{channel}"
        ch = stats["by_channel"].get(key, {})
        if family == "voice":
            limit = int(params.get("tentativas_por_hora", 6))
            recent = await count_recent_dispatches(
                db, activation.campaign_id, channel, since_hour
            )
            ch["hourly_quota_used"] = recent
            ch["hourly_quota_limit"] = limit
            ch["hourly_quota_remaining"] = remaining_hourly_quota(limit, recent)
        ch["slots_active"] = count_active_slots(aid, channel)
        ch["priority_queue_size"] = priority_queue_size(aid, channel)


async def _process_active_activations_async() -> dict:
    stats: dict = {
        "activations_processed": 0,
        "activations_in_window": 0,
        "leads_enqueued": 0,
        "followups_enqueued": 0,
        "leads_closed": 0,
        "priority_enqueued": 0,
        "priority_dispatched": 0,
        "by_channel": {},
    }

    since_hour = datetime.now(timezone.utc) - timedelta(hours=1)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentActivation)
            .where(AgentActivation.is_running.is_(True))
            .options(selectinload(AgentActivation.campaign).selectinload(Campaign.agent))
        )
        activations = list(result.scalars().all())

        in_window: list[AgentActivation] = []
        for activation in activations:
            stats["activations_processed"] += 1
            channel = normalize_channel_type(activation.channel_type)
            horario_inicio, horario_fim = await resolve_channel_window_params(
                db, activation.agent_id, channel
            )
            if not is_within_window(horario_inicio, horario_fim):
                logger.debug(
                    "Activation campaign=%s channel=%s outside window %s–%s",
                    activation.campaign_id,
                    channel,
                    horario_inicio,
                    horario_fim,
                )
                continue
            stats["activations_in_window"] += 1
            in_window.append(activation)

        groups: dict[tuple[uuid.UUID, str], list[AgentActivation]] = defaultdict(list)
        for activation in in_window:
            ch = normalize_channel_type(activation.channel_type)
            groups[(activation.agent_id, ch)].append(activation)

        for (agent_id, channel), group in groups.items():
            await _process_agent_channel_group(
                db, agent_id, channel, group, since_hour, stats
            )

        for key, ch_stats in stats["by_channel"].items():
            if any(
                ch_stats.get(k)
                for k in (
                    "first_message",
                    "followup",
                    "closed",
                    "skipped_slots",
                    "priority_dispatched",
                )
            ):
                logger.info("Scheduler %s stats=%s", key, ch_stats)

    logger.info(
        "process_active_activations: processed=%s in_window=%s enqueued=%s "
        "followups=%s closed=%s priority_out=%s priority_in=%s",
        stats["activations_processed"],
        stats["activations_in_window"],
        stats["leads_enqueued"],
        stats["followups_enqueued"],
        stats["leads_closed"],
        stats.get("priority_dispatched", 0),
        stats.get("priority_enqueued", 0),
    )
    return stats


@celery.task(name="worker.tasks.activation_scheduler.process_active_activations")
def process_active_activations() -> dict:
    """
    Enfileira leads com cadência (C), janela (B) e slots/fila de prioridade (D).

    Beat roda a cada 5 min (UTC); a checagem de janela usa America/Sao_Paulo.
    """
    return run_celery_async(_process_active_activations_async())
