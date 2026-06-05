"""
Persistência do ciclo de vida QueueEntry (R-B) — métricas de fila receptiva.

Redis = fila quente (R-A). Postgres = histórico para SLA, abandono (voz) e relatórios.

Registro de atendimentos receptivos:
  - IMEDIATO (sem fila): ANSWERED, wait_seconds=0 — conta no nível de serviço (0s).
  - COM FILA: WAITING → ANSWERED com wait_seconds = answered_at - enqueued_at.
  - ABANDONO: apenas canal VOZ (futuro inbound); mensageria nunca ABANDONED.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activation_defaults import MESSAGING_CHANNELS, normalize_channel_type
from app.core.config import settings
from app.models.queue_entry import QueueEntry, QueueEntryStatus

logger = logging.getLogger(__name__)

VOICE_CHANNEL = "voice"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _wait_seconds(enqueued_at: datetime, end: datetime) -> int:
    delta = end - enqueued_at
    return max(0, int(delta.total_seconds()))


async def get_waiting_entry(
    session: AsyncSession,
    channel_type: str,
    user_id: str,
) -> QueueEntry | None:
    ch = normalize_channel_type(channel_type)
    result = await session.execute(
        select(QueueEntry)
        .where(
            QueueEntry.channel_type == ch,
            QueueEntry.user_id == user_id,
            QueueEntry.status == QueueEntryStatus.WAITING,
        )
        .order_by(QueueEntry.enqueued_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def record_receptive_enqueue(
    session: AsyncSession,
    *,
    channel_type: str,
    user_id: str,
    agent_id: uuid.UUID | str,
    lead_id: uuid.UUID | None = None,
    enqueued_at: datetime | None = None,
) -> QueueEntry:
    """
    Cria QueueEntry WAITING ao entrar na fila Redis.

    Idempotente: se já existe WAITING para o contato, retorna o existente (score Redis
    pode atualizar mensagem, mas o registro histórico mantém enqueued_at original).
    """
    ch = normalize_channel_type(channel_type)
    existing = await get_waiting_entry(session, ch, user_id)
    if existing is not None:
        return existing

    now = enqueued_at if enqueued_at is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    aid = agent_id if isinstance(agent_id, uuid.UUID) else uuid.UUID(str(agent_id))
    entry = QueueEntry(
        channel_type=ch,
        user_id=user_id,
        lead_id=lead_id,
        agent_id=aid,
        enqueued_at=now,
        status=QueueEntryStatus.WAITING,
    )
    session.add(entry)
    await session.flush()
    logger.info(
        "QueueEntry WAITING channel=%s user=%s id=%s",
        ch,
        user_id,
        entry.id,
    )
    return entry


async def record_receptive_immediate_answer(
    session: AsyncSession,
    *,
    channel_type: str,
    user_id: str,
    agent_id: uuid.UUID | str,
    lead_id: uuid.UUID | None = None,
) -> QueueEntry:
    """
    Atendimento imediato (capacidade disponível, sem passar pela fila Redis).

    Registra ANSWERED com wait_seconds=0 para o SLA incluir atendimentos na hora.
    """
    now = _utc_now()
    aid = agent_id if isinstance(agent_id, uuid.UUID) else uuid.UUID(str(agent_id))
    entry = QueueEntry(
        channel_type=normalize_channel_type(channel_type),
        user_id=user_id,
        lead_id=lead_id,
        agent_id=aid,
        enqueued_at=now,
        answered_at=now,
        wait_seconds=0,
        status=QueueEntryStatus.ANSWERED,
    )
    session.add(entry)
    await session.flush()
    logger.info(
        "QueueEntry ANSWERED imediato channel=%s user=%s wait=0 id=%s",
        entry.channel_type,
        user_id,
        entry.id,
    )
    return entry


async def record_receptive_answered(
    session: AsyncSession,
    *,
    channel_type: str,
    user_id: str,
    agent_id: uuid.UUID | str | None = None,
    enqueued_at: datetime | None = None,
) -> QueueEntry | None:
    """
    Marca atendimento iniciado (saiu da fila / Beat ou fluxo com espera).

    Atualiza WAITING existente ou cria ANSWERED retroativo se não houver WAITING.
    """
    ch = normalize_channel_type(channel_type)
    now = _utc_now()
    aid: uuid.UUID | None = None
    if agent_id is not None:
        aid = agent_id if isinstance(agent_id, uuid.UUID) else uuid.UUID(str(agent_id))

    entry = await get_waiting_entry(session, ch, user_id)
    if entry is None:
        enq = enqueued_at if enqueued_at is not None else now
        if enq.tzinfo is None:
            enq = enq.replace(tzinfo=timezone.utc)
        entry = QueueEntry(
            channel_type=ch,
            user_id=user_id,
            agent_id=aid,
            enqueued_at=enq,
            answered_at=now,
            wait_seconds=_wait_seconds(enq, now),
            status=QueueEntryStatus.ANSWERED,
        )
        session.add(entry)
    else:
        if aid is not None:
            entry.agent_id = aid
        entry.answered_at = now
        entry.wait_seconds = _wait_seconds(entry.enqueued_at, now)
        entry.status = QueueEntryStatus.ANSWERED

    await session.flush()
    logger.info(
        "QueueEntry ANSWERED channel=%s user=%s wait=%ss id=%s",
        ch,
        user_id,
        entry.wait_seconds,
        entry.id,
    )
    return entry


async def mark_abandoned(
    session: AsyncSession,
    entry_id: uuid.UUID,
) -> QueueEntry | None:
    """
    Abandono na fila — APENAS VOZ.

    Será chamado pelo fluxo inbound de voz (futuro) ou sweep_queue_abandonment.
    Mensageria não deve usar esta função.
    """
    result = await session.execute(
        select(QueueEntry).where(QueueEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None

    if entry.channel_type in MESSAGING_CHANNELS:
        logger.warning(
            "mark_abandoned ignorado para mensageria channel=%s entry=%s",
            entry.channel_type,
            entry_id,
        )
        return entry

    if entry.channel_type != VOICE_CHANNEL:
        logger.warning(
            "mark_abandoned apenas para voz; channel=%s entry=%s",
            entry.channel_type,
            entry_id,
        )
        return entry

    if entry.status != QueueEntryStatus.WAITING:
        return entry

    now = _utc_now()
    entry.abandoned_at = now
    entry.wait_seconds = _wait_seconds(entry.enqueued_at, now)
    entry.status = QueueEntryStatus.ABANDONED
    await session.flush()
    logger.info(
        "QueueEntry ABANDONED (voz) channel=%s user=%s wait=%ss id=%s",
        entry.channel_type,
        entry.user_id,
        entry.wait_seconds,
        entry.id,
    )
    return entry


async def sweep_voice_queue_abandonment(session: AsyncSession) -> int:
    """
    Marca ABANDONED entradas WAITING de VOZ além do timeout.

    Hoje não há inbound de voz — em geral retorna 0. Mensageria é explicitamente
    excluída (não há abandono em WhatsApp/Telegram).
    """
    cutoff = _utc_now() - timedelta(seconds=settings.queue_abandon_timeout_seconds)
    result = await session.execute(
        select(QueueEntry).where(
            QueueEntry.status == QueueEntryStatus.WAITING,
            QueueEntry.channel_type == VOICE_CHANNEL,
            QueueEntry.enqueued_at < cutoff,
        )
    )
    entries = list(result.scalars().all())
    for entry in entries:
        await mark_abandoned(session, entry.id)
    if entries:
        logger.info("Sweep abandono voz: %s entradas marcadas ABANDONED", len(entries))
    return len(entries)
