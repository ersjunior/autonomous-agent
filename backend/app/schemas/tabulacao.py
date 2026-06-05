"""Pydantic schemas for tabulacoes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TabulacaoCategoriaLiteral = Literal["TELEFONIA", "NEGOCIO", "CUSTOMIZADO"]

CATEGORIAS_VALIDAS: frozenset[str] = frozenset({"TELEFONIA", "NEGOCIO", "CUSTOMIZADO"})


class TabulacaoCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    codigo: str = Field(min_length=1, max_length=50)
    categoria: TabulacaoCategoriaLiteral
    is_terminal: bool = False
    descricao: str | None = None

    @field_validator("codigo")
    @classmethod
    def codigo_nao_vazio(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("codigo não pode ser vazio")
        return stripped

    @field_validator("categoria")
    @classmethod
    def categoria_valida(cls, value: str) -> str:
        if value not in CATEGORIAS_VALIDAS:
            raise ValueError("categoria deve ser TELEFONIA, NEGOCIO ou CUSTOMIZADO")
        return value


class TabulacaoUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=255)
    codigo: str | None = Field(default=None, min_length=1, max_length=50)
    categoria: TabulacaoCategoriaLiteral | None = None
    is_terminal: bool | None = None
    descricao: str | None = None

    @field_validator("codigo")
    @classmethod
    def codigo_nao_vazio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("codigo não pode ser vazio")
        return stripped

    @field_validator("categoria")
    @classmethod
    def categoria_valida(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in CATEGORIAS_VALIDAS:
            raise ValueError("categoria deve ser TELEFONIA, NEGOCIO ou CUSTOMIZADO")
        return value


class TabulacaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    nome: str
    codigo: str
    categoria: str
    is_terminal: bool
    is_system: bool = False
    descricao: str | None
    created_at: datetime


class TabulacaoCatalogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    codigo: str
    categoria: str
    is_terminal: bool
