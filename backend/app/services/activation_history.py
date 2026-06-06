"""Queries and finalize logic for outbound activation history."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import can_view
from app.models.campaign import Campaign
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.models.user import User
from app.schemas.activation import ActivationHistoryItem, FinalizeInteractionResponse
from app.services.human_handoff import finalize_human_mode, is_in_human_mode
from app.services.tabulacao_assignment import apply_tabulacao
from app.services.tabulacao_mapping import status_from_tabulacao_codigo
from app.services.capacity_service import release_outbound_capacity_for_lead
from app.services.activation_slots import release_slot_for_lead
from worker.tasks.conversation_routing import TERMINAL_STATUSES
from worker.tasks.outbound_campaign import _resolve_recipient

HISTORY_STATUS_VALUES = (
    "pendente",
    "acionado",
    "em_andamento",
    "convertido",
    "recusou",
    "nao_atendido",
    "erro",
)


def campaign_visibility_filter(user: User):
    return or_(Campaign.is_system.is_(True), Campaign.user_id == user.id)


def _is_terminal_status(status_value: str | None) -> bool:
    return (status_value or "").lower() in TERMINAL_STATUSES


def _to_history_item(record: LeadInteraction, *, channel_user_id: str | None) -> ActivationHistoryItem:
    lead = record.lead
    campaign = record.campaign
    tab = record.tabulacao
    ch = record.channel_type
    in_human = (
        is_in_human_mode(ch, channel_user_id)
        if channel_user_id
        else False
    )
    return ActivationHistoryItem(
        id=record.id,
        lead_id=record.lead_id,
        lead_nome=lead.nome_cliente if lead else "—",
        campaign_id=record.campaign_id,
        campaign_name=campaign.name if campaign else "—",
        channel_type=ch,
        status=record.status,
        tentativas=record.tentativas,
        data_acionamento=record.data_acionamento,
        data_ultimo_contato=record.data_ultimo_contato,
        data_ultima_tentativa=record.data_ultima_tentativa,
        tabulacao_codigo=tab.codigo if tab else None,
        tabulacao_nome=tab.nome if tab else None,
        tabulacao_aplicada_em=record.tabulacao_aplicada_em,
        is_terminal=_is_terminal_status(record.status),
        is_human_mode=in_human,
    )


def _history_base_stmt(user: User):
    return (
        select(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(
            LeadInteraction.data_acionamento.isnot(None),
            campaign_visibility_filter(user),
        )
    )


def apply_history_filters(
    stmt,
    *,
    campaign_id: uuid.UUID | None,
    channel_type: str | None,
    status_filter: str | None,
    open_only: bool,
):
    if campaign_id is not None:
        stmt = stmt.where(LeadInteraction.campaign_id == campaign_id)
    if channel_type is not None:
        stmt = stmt.where(LeadInteraction.channel_type == channel_type)
    if status_filter is not None:
        stmt = stmt.where(LeadInteraction.status == status_filter.lower())
    if open_only:
        stmt = stmt.where(LeadInteraction.status.notin_(tuple(TERMINAL_STATUSES)))
    return stmt


async def list_activation_history(
    db: AsyncSession,
    user: User,
    *,
    skip: int,
    limit: int,
    campaign_id: uuid.UUID | None = None,
    channel_type: str | None = None,
    status_filter: str | None = None,
    open_only: bool = False,
) -> tuple[list[ActivationHistoryItem], int]:
    base = _history_base_stmt(user)
    filtered = apply_history_filters(
        base,
        campaign_id=campaign_id,
        channel_type=channel_type,
        status_filter=status_filter,
        open_only=open_only,
    )

    total = await db.scalar(select(func.count()).select_from(filtered.subquery())) or 0

    result = await db.execute(
        filtered.options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign),
            selectinload(LeadInteraction.tabulacao),
        )
        .order_by(
            LeadInteraction.data_acionamento.desc().nullslast(),
            LeadInteraction.created_at.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    records = list(result.scalars().unique().all())

    items: list[ActivationHistoryItem] = []
    for record in records:
        channel_user_id = None
        if record.lead is not None:
            channel_user_id = _resolve_recipient(record.lead, record.channel_type)
        items.append(_to_history_item(record, channel_user_id=channel_user_id))

    return items, int(total)


async def get_lead_interaction_for_user(
    db: AsyncSession,
    interaction_id: uuid.UUID,
    user: User,
) -> LeadInteraction:
    result = await db.execute(
        select(LeadInteraction)
        .options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign),
            selectinload(LeadInteraction.tabulacao),
        )
        .where(LeadInteraction.id == interaction_id)
    )
    record = result.scalar_one_or_none()
    if record is None or record.campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead interaction not found",
        )
    if not can_view(record.campaign, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead interaction not found",
        )
    return record


async def validate_tabulacao_codigo_for_user(
    db: AsyncSession,
    user: User,
    codigo: str,
) -> None:
    normalized = codigo.strip().upper()
    result = await db.execute(
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


async def finalize_lead_interaction_manual(
    db: AsyncSession,
    record: LeadInteraction,
    *,
    tabulacao_codigo: str,
    status_interno: str | None = None,
) -> FinalizeInteractionResponse:
    if _is_terminal_status(record.status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Atendimento já encerrado",
        )

    codigo = tabulacao_codigo.strip().upper()
    terminal_status = (status_interno or status_from_tabulacao_codigo(codigo)).lower()
    record.status = terminal_status

    applied = await apply_tabulacao(
        db,
        record,
        status_interno=terminal_status,
        channel=record.channel_type,
        origem="MANUAL_FINALIZE",
        tabulacao_codigo=codigo,
    )
    if not applied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não foi possível aplicar a tabulação {codigo}",
        )

    release_outbound_capacity_for_lead(str(record.lead_id), record.channel_type)
    release_slot_for_lead(str(record.lead_id), record.channel_type)

    if record.lead is not None:
        channel_user_id = _resolve_recipient(record.lead, record.channel_type)
        if channel_user_id and is_in_human_mode(record.channel_type, channel_user_id):
            finalize_human_mode(record.channel_type, channel_user_id)

    await db.flush()

    return FinalizeInteractionResponse(
        ok=True,
        lead_interaction_id=record.id,
        status=terminal_status,
        tabulacao_codigo=codigo,
        message="Atendimento finalizado",
    )
