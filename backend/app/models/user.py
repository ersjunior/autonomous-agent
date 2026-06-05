"""User model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    agents: Mapped[list[Agent]] = relationship(back_populates="user", cascade="all, delete-orphan")
    channels: Mapped[list[Channel]] = relationship(back_populates="user", cascade="all, delete-orphan")
    leads: Mapped[list[Lead]] = relationship(back_populates="user", cascade="all, delete-orphan")
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tabulacoes: Mapped[list["Tabulacao"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )