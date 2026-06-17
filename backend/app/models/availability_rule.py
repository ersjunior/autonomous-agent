"""Availability rules for appointment slot generation (Fase D)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AvailabilityRule(Base):
    """
    Regras de disponibilidade por tenant e opcionalmente por agente.

    - agent_id NULL → regra do tenant (user_id).
    - agent_id preenchido → regra do agente (substitui o nível tenant).

    Nota: por ora existe no máximo 1 faixa por (user_id, agent_id, weekday).
    TODO(Fase futura): suportar múltiplas faixas por dia (ex.: 09:00–12:00 e 14:00–18:00).
    """

    __tablename__ = "availability_rules"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "agent_id",
            "weekday",
            name="uq_availability_rules_user_agent_weekday",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_availability_rules_user_agent_weekday_active",
            "user_id",
            "agent_id",
            "weekday",
            postgresql_where=sa.text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    slot_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

