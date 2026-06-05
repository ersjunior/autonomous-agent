"""Tabulacao CRUD API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import raise_if_cannot_delete, raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.tabulacao import Tabulacao, TabulacaoCategoria
from app.models.user import User
from app.schemas.tabulacao import (
    TabulacaoCatalogItem,
    TabulacaoCreate,
    TabulacaoResponse,
    TabulacaoUpdate,
)

router = APIRouter(prefix="/tabulacoes", tags=["tabulacoes"])


async def _get_tabulacao(
    tabulacao_id: uuid.UUID, user: User, db: AsyncSession
) -> Tabulacao:
    result = await db.execute(select(Tabulacao).where(Tabulacao.id == tabulacao_id))
    tabulacao = result.scalar_one_or_none()
    if tabulacao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tabulação not found")
    raise_if_cannot_view(tabulacao, user, not_found_detail="Tabulação not found")
    return tabulacao


def _resolve_categoria(categoria: str) -> str:
    try:
        TabulacaoCategoria(categoria)
    except ValueError:
        return TabulacaoCategoria.CUSTOMIZADO.value
    return categoria


@router.get("/", response_model=list[TabulacaoResponse])
async def list_tabulacoes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Tabulacao]:
    result = await db.execute(
        select(Tabulacao).where(
            or_(Tabulacao.is_system.is_(True), Tabulacao.user_id == user.id)
        )
    )
    return list(result.scalars().all())


@router.get("/catalog", response_model=list[TabulacaoCatalogItem])
async def list_tabulacoes_catalog(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Tabulacao]:
    result = await db.execute(
        select(Tabulacao).where(
            or_(Tabulacao.is_system.is_(True), Tabulacao.user_id == user.id)
        )
    )
    return list(result.scalars().all())


@router.post("/", response_model=TabulacaoResponse, status_code=status.HTTP_201_CREATED)
async def create_tabulacao(
    payload: TabulacaoCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tabulacao:
    tabulacao = Tabulacao(
        user_id=user.id,
        nome=payload.nome,
        codigo=payload.codigo,
        categoria=_resolve_categoria(payload.categoria),
        is_terminal=payload.is_terminal,
        descricao=payload.descricao,
        is_system=False,
    )
    db.add(tabulacao)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if "uq_tabulacoes_codigo" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Código de tabulação já existe",
            ) from exc
        raise
    await db.refresh(tabulacao)
    return tabulacao


@router.get("/{tabulacao_id}", response_model=TabulacaoResponse)
async def get_tabulacao(
    tabulacao_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tabulacao:
    return await _get_tabulacao(tabulacao_id, user, db)


@router.put("/{tabulacao_id}", response_model=TabulacaoResponse)
async def update_tabulacao(
    tabulacao_id: uuid.UUID,
    payload: TabulacaoUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tabulacao:
    tabulacao = await _get_tabulacao(tabulacao_id, user, db)
    raise_if_cannot_edit(tabulacao, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "categoria" and value is not None:
            setattr(tabulacao, field, _resolve_categoria(value))
        else:
            setattr(tabulacao, field, value)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if "uq_tabulacoes_codigo" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Código de tabulação já existe",
            ) from exc
        raise
    await db.refresh(tabulacao)
    return tabulacao


@router.delete("/{tabulacao_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tabulacao(
    tabulacao_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    tabulacao = await _get_tabulacao(tabulacao_id, user, db)
    raise_if_cannot_delete(tabulacao, user)
    await db.delete(tabulacao)
    await db.commit()
