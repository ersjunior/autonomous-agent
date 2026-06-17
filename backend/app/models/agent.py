"""Agent model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.agent_activation import AgentActivation
    from app.models.agent_channel_settings import AgentChannelSettings
    from app.models.appointment import Appointment
    from app.models.campaign import Campaign
    from app.models.user import User


class AgentMode(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RECEPTIVE = "RECEPTIVE"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[AgentMode] = mapped_column(Enum(AgentMode, name="agent_mode"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user: Mapped[User] = relationship(back_populates="agents")
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="agent")
    channel_settings: Mapped[list["AgentChannelSettings"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    activations: Mapped[list["AgentActivation"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="agent")
