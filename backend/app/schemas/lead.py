"""Pydantic schemas for leads."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LeadCreate(BaseModel):
    lead_base_id: UUID
    id_cliente: str | None = Field(default=None, max_length=255)
    nome_cliente: str = Field(min_length=1, max_length=255)
    cpf_cliente: str | None = Field(default=None, max_length=14)
    email_cliente: str | None = Field(default=None, max_length=255)
    telefone_1: str | None = Field(default=None, max_length=50)
    telefone_2: str | None = Field(default=None, max_length=50)
    telefone_3: str | None = Field(default=None, max_length=50)
    aux_values: dict[str, Any] = Field(default_factory=dict)


class LeadUpdate(BaseModel):
    id_cliente: str | None = Field(default=None, max_length=255)
    nome_cliente: str | None = Field(default=None, min_length=1, max_length=255)
    cpf_cliente: str | None = Field(default=None, max_length=14)
    email_cliente: str | None = Field(default=None, max_length=255)
    telefone_1: str | None = Field(default=None, max_length=50)
    telefone_2: str | None = Field(default=None, max_length=50)
    telefone_3: str | None = Field(default=None, max_length=50)
    aux_values: dict[str, Any] | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lead_base_id: UUID
    id_cliente: str | None
    nome_cliente: str
    cpf_cliente: str | None
    email_cliente: str | None
    telefone_1: str | None
    telefone_2: str | None
    telefone_3: str | None
    aux_values: dict[str, Any]
    is_system: bool = False
    created_at: datetime


class LeadListResponse(BaseModel):
    items: list[LeadResponse]
    total: int
    skip: int
    limit: int
