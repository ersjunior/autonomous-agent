"""LeadBase model and lead_base_channels association."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.lead import Lead


class LeadBaseChannel(Base):
    __tablename__ = "lead_base_channels"

    lead_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_bases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    channel_type: Mapped[str] = mapped_column(String(50), primary_key=True)

    lead_base: Mapped[LeadBase] = relationship(back_populates="lead_base_channels")


class LeadBase(Base):
    __tablename__ = "lead_bases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    data_recebimento: Mapped[date] = mapped_column(Date, nullable=False)
    data_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    campaign: Mapped[Campaign] = relationship(back_populates="lead_bases")
    leads: Mapped[list[Lead]] = relationship(back_populates="lead_base", cascade="all, delete-orphan")
    lead_base_channels: Mapped[list[LeadBaseChannel]] = relationship(
        back_populates="lead_base",
        cascade="all, delete-orphan",
    )
