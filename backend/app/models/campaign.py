"""Campaign model and campaign_channels association."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.lead_base import LeadBase
    from app.models.lead_interaction import LeadInteraction
    from app.models.user import User


class CampaignChannel(Base):
    __tablename__ = "campaign_channels"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    channel_type: Mapped[str] = mapped_column(String(50), primary_key=True)

    campaign: Mapped[Campaign] = relationship(back_populates="campaign_channels")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    leads_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="campaigns")
    agent: Mapped[Agent] = relationship(back_populates="campaigns")
    campaign_channels: Mapped[list[CampaignChannel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    lead_bases: Mapped[list[LeadBase]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    lead_interactions: Mapped[list[LeadInteraction]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
