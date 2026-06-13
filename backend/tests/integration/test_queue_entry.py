"""Integração — ciclo QueueEntry (enqueue → answered / abandoned, wait_seconds, sweep voz)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.queue_entry import QueueEntry, QueueEntryStatus
from app.services.queue_entry_service import (
    mark_abandoned,
    record_receptive_answered,
    record_receptive_enqueue,
    record_receptive_immediate_answer,
    sweep_voice_queue_abandonment,
)
from app.services.queue_metrics import get_queue_metrics
from tests.integration.helpers import OwnerContext

pytestmark = pytest.mark.integration

BASE_TIME = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def queue_clock(monkeypatch):
    """Relógio determinístico para wait_seconds e sweep (patch em _utc_now)."""
    state = {"now": BASE_TIME}

    def fake_utc_now() -> datetime:
        return state["now"]

    def advance(seconds: int) -> None:
        state["now"] = state["now"] + timedelta(seconds=seconds)

    def set_now(moment: datetime) -> None:
        state["now"] = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    monkeypatch.setattr("app.services.queue_entry_service._utc_now", fake_utc_now)
    state["advance"] = advance
    state["set_now"] = set_now
    return state


def _contact(suffix: str | None = None) -> str:
    return f"queue-{suffix or uuid.uuid4().hex[:8]}"


async def _count_entries(session, **filters) -> int:
    stmt = select(func.count()).select_from(QueueEntry)
    for key, value in filters.items():
        stmt = stmt.where(getattr(QueueEntry, key) == value)
    return await session.scalar(stmt)


# --- 1. ENQUEUE ---


async def test_enqueue_creates_waiting_entry(
    owner_ctx: OwnerContext, db_session, queue_clock
) -> None:
    user_id = _contact("enqueue")
    enqueued_at = queue_clock["now"]

    entry = await record_receptive_enqueue(
        db_session,
        channel_type="whatsapp",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        lead_id=owner_ctx.lead.id,
        enqueued_at=enqueued_at,
    )

    assert entry.id is not None
    assert entry.status == QueueEntryStatus.WAITING
    assert entry.enqueued_at == enqueued_at
    assert entry.answered_at is None
    assert entry.abandoned_at is None
    assert entry.wait_seconds is None
    assert entry.channel_type == "whatsapp"
    assert entry.lead_id == owner_ctx.lead.id


async def test_enqueue_is_idempotent_for_same_contact(
    owner_ctx: OwnerContext, db_session, queue_clock
) -> None:
    user_id = _contact("idem")
    first = await record_receptive_enqueue(
        db_session,
        channel_type="telegram",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        enqueued_at=queue_clock["now"],
    )
    queue_clock["advance"](30)
    second = await record_receptive_enqueue(
        db_session,
        channel_type="telegram",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
    )

    assert second.id == first.id
    assert second.enqueued_at == first.enqueued_at
    assert await _count_entries(db_session, user_id=user_id) == 1


# --- 2. IMMEDIATE ANSWER ---


async def test_immediate_answer_creates_answered_zero_wait(
    owner_ctx: OwnerContext, db_session, queue_clock
) -> None:
    user_id = _contact("immediate")
    now = queue_clock["now"]

    entry = await record_receptive_immediate_answer(
        db_session,
        channel_type="whatsapp",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        lead_id=owner_ctx.lead.id,
    )

    assert entry.status == QueueEntryStatus.ANSWERED
    assert entry.wait_seconds == 0
    assert entry.enqueued_at == now
    assert entry.answered_at == now
    assert entry.abandoned_at is None


# --- 3. ANSWERED após espera ---


async def test_answered_after_wait_calculates_wait_seconds(
    owner_ctx: OwnerContext, db_session, queue_clock
) -> None:
    user_id = _contact("wait")
    enqueued_at = queue_clock["now"]

    waiting = await record_receptive_enqueue(
        db_session,
        channel_type="whatsapp",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        enqueued_at=enqueued_at,
    )

    queue_clock["advance"](45)

    answered = await record_receptive_answered(
        db_session,
        channel_type="whatsapp",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
    )

    assert answered is not None
    assert answered.id == waiting.id
    assert answered.status == QueueEntryStatus.ANSWERED
    assert answered.answered_at == queue_clock["now"]
    assert answered.wait_seconds == 45


async def test_answered_retroactive_when_no_waiting_entry(
    owner_ctx: OwnerContext, db_session, queue_clock
) -> None:
    user_id = _contact("retro")
    enqueued_at = queue_clock["now"]
    queue_clock["advance"](20)

    entry = await record_receptive_answered(
        db_session,
        channel_type="telegram",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        enqueued_at=enqueued_at,
    )

    assert entry is not None
    assert entry.status == QueueEntryStatus.ANSWERED
    assert entry.wait_seconds == 20


# --- 4. ABANDONED (voz) ---


async def test_mark_abandoned_voice_sets_abandoned(
    owner_ctx: OwnerContext, db_session, queue_clock
) -> None:
    user_id = _contact("voice-abandon")
    enqueued_at = queue_clock["now"]

    entry = await record_receptive_enqueue(
        db_session,
        channel_type="voice",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        enqueued_at=enqueued_at,
    )

    queue_clock["advance"](25)

    result = await mark_abandoned(db_session, entry.id)

    assert result is not None
    assert result.status == QueueEntryStatus.ABANDONED
    assert result.abandoned_at == queue_clock["now"]
    assert result.wait_seconds == 25


# --- 5. Mensageria nunca abandona ---


@pytest.mark.parametrize("channel", ["whatsapp", "telegram"])
async def test_mark_abandoned_ignores_messaging(
    owner_ctx: OwnerContext, db_session, queue_clock, channel: str
) -> None:
    user_id = _contact(f"msg-{channel}")
    entry = await record_receptive_enqueue(
        db_session,
        channel_type=channel,
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        enqueued_at=queue_clock["now"] - timedelta(hours=2),
    )

    result = await mark_abandoned(db_session, entry.id)

    assert result is not None
    assert result.status == QueueEntryStatus.WAITING
    assert result.abandoned_at is None
    assert result.wait_seconds is None


# --- 6. sweep_voice_queue_abandonment ---


async def test_sweep_abandons_stale_voice_only(
    owner_ctx: OwnerContext, db_session, queue_clock, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.queue_abandon_timeout_seconds", 60)

    stale_voice = await record_receptive_enqueue(
        db_session,
        channel_type="voice",
        user_id=_contact("stale-voice"),
        agent_id=owner_ctx.agent.id,
        enqueued_at=queue_clock["now"] - timedelta(seconds=120),
    )
    recent_voice = await record_receptive_enqueue(
        db_session,
        channel_type="voice",
        user_id=_contact("recent-voice"),
        agent_id=owner_ctx.agent.id,
        enqueued_at=queue_clock["now"] - timedelta(seconds=10),
    )
    stale_whatsapp = await record_receptive_enqueue(
        db_session,
        channel_type="whatsapp",
        user_id=_contact("stale-wa"),
        agent_id=owner_ctx.agent.id,
        enqueued_at=queue_clock["now"] - timedelta(seconds=120),
    )

    swept = await sweep_voice_queue_abandonment(db_session)

    assert swept == 1
    await db_session.refresh(stale_voice)
    await db_session.refresh(recent_voice)
    await db_session.refresh(stale_whatsapp)

    assert stale_voice.status == QueueEntryStatus.ABANDONED
    assert stale_voice.abandoned_at == queue_clock["now"]
    assert recent_voice.status == QueueEntryStatus.WAITING
    assert stale_whatsapp.status == QueueEntryStatus.WAITING


async def test_sweep_does_not_re_abandon_answered_voice(
    owner_ctx: OwnerContext, db_session, queue_clock, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.queue_abandon_timeout_seconds", 60)
    user_id = _contact("answered-voice")

    entry = await record_receptive_enqueue(
        db_session,
        channel_type="voice",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
        enqueued_at=queue_clock["now"] - timedelta(seconds=120),
    )
    await record_receptive_answered(
        db_session,
        channel_type="voice",
        user_id=user_id,
        agent_id=owner_ctx.agent.id,
    )

    swept = await sweep_voice_queue_abandonment(db_session)

    assert swept == 0
    await db_session.refresh(entry)
    assert entry.status == QueueEntryStatus.ANSWERED


# --- 7. Métricas básicas ---


async def test_queue_metrics_aggregates_known_entries(
    owner_ctx: OwnerContext, db_session, queue_clock, monkeypatch
) -> None:
    monkeypatch.setattr("app.services.queue_metrics.queue_size", lambda _ch: 0)
    monkeypatch.setattr(
        "app.services.queue_metrics._period_start",
        lambda days: BASE_TIME - timedelta(days=max(1, days)),
    )

    t0 = BASE_TIME - timedelta(hours=2)

    queue_clock["set_now"](BASE_TIME)
    await record_receptive_immediate_answer(
        db_session,
        channel_type="whatsapp",
        user_id=_contact("m-immediate"),
        agent_id=owner_ctx.agent.id,
    )

    queue_clock["set_now"](t0)
    wa_waiting = await record_receptive_enqueue(
        db_session,
        channel_type="whatsapp",
        user_id=_contact("m-wait"),
        agent_id=owner_ctx.agent.id,
        enqueued_at=t0,
    )
    queue_clock["advance"](30)
    await record_receptive_answered(
        db_session,
        channel_type="whatsapp",
        user_id=wa_waiting.user_id,
        agent_id=owner_ctx.agent.id,
    )

    queue_clock["set_now"](t0)
    voice_entry = await record_receptive_enqueue(
        db_session,
        channel_type="voice",
        user_id=_contact("m-voice"),
        agent_id=owner_ctx.agent.id,
        enqueued_at=t0,
    )
    queue_clock["advance"](60)
    await mark_abandoned(db_session, voice_entry.id)

    queue_clock["set_now"](BASE_TIME)
    metrics = await get_queue_metrics(db_session, days=1)

    assert metrics.total_atendidos >= 2
    assert metrics.total_abandonados >= 1
    assert metrics.total_enfileirados >= 2
    assert metrics.tempo_medio_espera == 30.0
    assert metrics.por_canal["whatsapp"].total_atendidos >= 2
    assert metrics.por_canal["voice"].total_abandonados >= 1
    assert metrics.abandono_apenas_voz is True
