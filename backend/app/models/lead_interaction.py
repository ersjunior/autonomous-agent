"""LeadInteraction model — acionamento e resultado de atendimento por lead/canal."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.interaction import Interaction
    from app.models.lead import Lead


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
    data_ultimo_contato: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    lead: Mapped[Lead] = relationship(back_populates="lead_interactions")
    campaign: Mapped[Campaign] = relationship(back_populates="lead_interactions")
    last_interaction: Mapped[Interaction | None] = relationship(foreign_keys=[last_interaction_id])
