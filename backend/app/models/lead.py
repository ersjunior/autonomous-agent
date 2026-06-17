"""Lead model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.lead_base import LeadBase
    from app.models.lead_interaction import LeadInteraction
    from app.models.user import User


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    lead_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    id_cliente: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nome_cliente: Mapped[str] = mapped_column(String(255), nullable=False)
    cpf_cliente: Mapped[str | None] = mapped_column(String(14), nullable=True)
    email_cliente: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telefone_1: Mapped[str | None] = mapped_column(String(50), nullable=True)
    telefone_2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    telefone_3: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aux_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="leads")
    lead_base: Mapped[LeadBase] = relationship(back_populates="leads")
    lead_interactions: Mapped[list[LeadInteraction]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
    )
