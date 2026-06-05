"""Tabulacao model — classificação de resultado de atendimento."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.lead_interaction import LeadInteraction
    from app.models.user import User


class TabulacaoCategoria(str, enum.Enum):
    TELEFONIA = "TELEFONIA"
    NEGOCIO = "NEGOCIO"
    CUSTOMIZADO = "CUSTOMIZADO"


class Tabulacao(Base):
    __tablename__ = "tabulacoes"
    __table_args__ = (UniqueConstraint("codigo", name="uq_tabulacoes_codigo"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False)
    categoria: Mapped[TabulacaoCategoria] = mapped_column(
        String(50),
        nullable=False,
    )
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="tabulacoes")
    lead_interactions: Mapped[list[LeadInteraction]] = relationship(back_populates="tabulacao")
