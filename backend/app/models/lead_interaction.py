"""LeadInteraction model — acionamento e resultado de atendimento por lead/canal."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.interaction import Interaction
    from app.models.lead import Lead
    from app.models.tabulacao import Tabulacao


class LeadInteraction(Base):
    __tablename__ = "lead_interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pendente", nullable=False)
    devolutiva: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_acionamento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_ultimo_contato: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Último inbound do lead neste canal (base para detectar resposta).",
    )
    tentativas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_ultima_tentativa: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp do último outbound (1ª msg ou follow-up).",
    )
    last_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    tabulacao_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tabulacoes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tabulacao_origem: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Origem da tabulação: INTENT, IA, SIP ou MANUAL (preenchido na T-2).",
    )
    tabulacao_aplicada_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp em que a tabulação foi aplicada (preenchido na T-2).",
    )
    twilio_call_sid: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Call SID Twilio para correlação SIP (gancho futuro).",
    )
    lifecycle_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="0 = legado (fora do sweep de inatividade); >=1 = regras novas.",
    )
    inactivity_warning_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp do aviso 'Ainda está aí?' (resetado quando o cliente responde).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    lead: Mapped[Lead] = relationship(back_populates="lead_interactions")
    campaign: Mapped[Campaign] = relationship(back_populates="lead_interactions")
    last_interaction: Mapped[Interaction | None] = relationship(foreign_keys=[last_interaction_id])
    tabulacao: Mapped[Tabulacao | None] = relationship(back_populates="lead_interactions")
