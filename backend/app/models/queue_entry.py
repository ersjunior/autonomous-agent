"""
QueueEntry — histórico do ciclo de vida da fila receptiva (R-B).

Estado quente da fila: Redis (R-A). Esta tabela persiste métricas de call center.

Ciclo de vida:
  - Atendimento IMEDIATO (sem fila): ANSWERED, wait_seconds=0, enqueued_at=answered_at.
  - Com fila: WAITING ao enfileirar → ANSWERED ao iniciar atendimento.
  - Abandono: só VOZ (lead desligou na fila). Mensageria não abandona — só espera/SLA.

Abandono fica implementado (mark_abandoned + sweep) mas sem dados reais até inbound de voz.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueueEntryStatus(str, enum.Enum):
    WAITING = "WAITING"
    ANSWERED = "ANSWERED"
    ABANDONED = "ABANDONED"


class QueueEntry(Base):
    __tablename__ = "queue_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    abandoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wait_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[QueueEntryStatus] = mapped_column(
        Enum(QueueEntryStatus, name="queue_entry_status"),
        nullable=False,
        default=QueueEntryStatus.WAITING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
