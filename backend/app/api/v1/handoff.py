"""API — modo humano (handoff B-2 + H-2)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.tabulacao import Tabulacao
from app.models.user import User
from app.schemas.handoff import (
    HandoffActionResponse,
    HandoffAssumeRequest,
    HandoffContact,
    HandoffFinalizeRequest,
    HandoffReactivateRequest,
    HandoffReactivateResponse,
)
from app.services.human_handoff import (
    assume_human_mode,
    exit_human_mode,
    finalize_handoff_lead,
    is_in_human_mode,
    list_active_human_mode_contacts,
    resolve_handoff_owner,
)
from worker.tasks.lead_tracking import find_lead_by_channel_user

router = APIRouter(prefix="/handoff", tags=["handoff"])

_HANDOFF_NOT_FOUND = "Contato não está em modo humano"


async def _validate_tabulacao_codigo(
    session: AsyncSession,
    user: User,
    codigo: str,
) -> None:
    normalized = codigo.strip().upper()
    result = await session.execute(
        select(Tabulacao.id).where(
            Tabulacao.codigo == normalized,
            or_(Tabulacao.is_system.is_(True), Tabulacao.user_id == user.id),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tabulação inválida ou não encontrada: {normalized}",
        )


def _lead_display_name(lead, user_id: str) -> str | None:
    if lead is None:
        return None
    name = (getattr(lead, "nome_cliente", None) or "").strip()
    return name or None


async def _assert_handoff_owner(
    db: AsyncSession,
    user: User,
    channel: str,
    contact_user_id: str,
) -> None:
    """Dono do handoff deve ser o usuário autenticado; senão 404 (sem vazar existência)."""
    if not is_in_human_mode(channel, contact_user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_HANDOFF_NOT_FOUND,
        )
    owner_id = await resolve_handoff_owner(db, channel, contact_user_id)
    if owner_id is None or owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_HANDOFF_NOT_FOUND,
        )


async def _handoff_visible_to_user(
    db: AsyncSession,
    user: User,
    row: dict,
) -> bool:
    owner_id = await resolve_handoff_owner(
        db,
        row["channel"],
        row["user_id"],
        owner_user_id_from_payload=row.get("owner_user_id"),
    )
    return owner_id is not None and owner_id == user.id


@router.get("/active", response_model=list[HandoffContact])
async def list_active_handoffs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HandoffContact]:
    """Contatos aguardando atendente humano (chaves human_mode:* no Redis) do tenant."""
    rows = list_active_human_mode_contacts()
    contacts: list[HandoffContact] = []
    for row in rows:
        if not await _handoff_visible_to_user(db, user, row):
            continue
        lead = await find_lead_by_channel_user(db, row["channel"], row["user_id"])
        contacts.append(
            HandoffContact(
                channel=row["channel"],
                user_id=row["user_id"],
                lead_name=_lead_display_name(lead, row["user_id"]),
                escalated_at=(
                    datetime.fromisoformat(row["escalated_at"])
                    if row.get("escalated_at")
                    else None
                ),
                human_assumed_at=(
                    datetime.fromisoformat(row["human_assumed_at"])
                    if row.get("human_assumed_at")
                    else None
                ),
                assumed_by=row.get("assumed_by"),
                is_assumed=bool(row.get("is_assumed")),
                ttl_seconds=row.get("ttl_seconds"),
            )
        )
    return contacts


@router.post("/assume", response_model=HandoffActionResponse)
async def assume_handoff(
    payload: HandoffAssumeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HandoffActionResponse:
    """Operador assume o atendimento humano (estende TTL para finalize_ttl)."""
    await _assert_handoff_owner(db, user, payload.channel, payload.user_id)
    assumed_by = user.email or str(user.id)
    ok = assume_human_mode(
        payload.channel,
        payload.user_id,
        assumed_by=assumed_by,
    )
    return HandoffActionResponse(
        ok=ok,
        channel=payload.channel,
        user_id=payload.user_id,
        message="Atendimento assumido" if ok else "Falha ao assumir",
    )


@router.post("/finalize", response_model=HandoffActionResponse)
async def finalize_handoff(
    payload: HandoffFinalizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HandoffActionResponse:
    """Encerra handoff com tabulação escolhida pelo operador."""
    await _assert_handoff_owner(db, user, payload.channel, payload.user_id)
    await _validate_tabulacao_codigo(db, user, payload.tabulacao_codigo)
    ok = await finalize_handoff_lead(
        db,
        channel=payload.channel,
        user_id=payload.user_id,
        tabulacao_codigo=payload.tabulacao_codigo.strip().upper(),
        status_interno=payload.status_interno,
        origem="HANDOFF_FINALIZE",
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado para finalizar o handoff",
        )
    await db.commit()
    return HandoffActionResponse(
        ok=True,
        channel=payload.channel,
        user_id=payload.user_id,
        message="Handoff finalizado",
    )


@router.post("/reactivate", response_model=HandoffReactivateResponse)
async def reactivate_from_human_mode(
    payload: HandoffReactivateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HandoffReactivateResponse:
    """Operador devolve o contato ao bot (remove modo humano)."""
    if is_in_human_mode(payload.channel, payload.user_id):
        await _assert_handoff_owner(db, user, payload.channel, payload.user_id)
    reactivated = exit_human_mode(payload.channel, payload.user_id)
    return HandoffReactivateResponse(
        reactivated=reactivated,
        channel=payload.channel,
        user_id=payload.user_id,
    )
