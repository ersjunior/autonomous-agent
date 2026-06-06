"""Agent channel settings and campaign activation (motor Layer A)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activation_defaults import (
    SUPPORTED_CHANNEL_TYPES,
    normalize_channel_type,
)
from app.core.authorization import raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from app.models.user import User
from app.schemas.activation import (
    ActivationHistoryListResponse,
    ActivationListResponse,
    ActivationResponse,
    ActivationStartResponse,
    ChannelSettingsListResponse,
    ChannelSettingsResponse,
    ChannelSettingsUpdate,
    FinalizeInteractionRequest,
    FinalizeInteractionResponse,
    TestDispatchRequest,
    TestDispatchResponse,
)
from app.services.activation_history import (
    HISTORY_STATUS_VALUES,
    finalize_lead_interaction_manual,
    get_lead_interaction_for_user,
    list_activation_history,
    validate_tabulacao_codigo_for_user,
)
from app.core.activation_window import is_within_window, outside_window_reason
from app.services.activation_service import (
    build_channel_settings_response,
    dispatch_campaign_leads_for_channel,
    ensure_active_agent,
    ensure_campaign_channel,
    get_agent_channel_settings_row,
    list_agent_channel_settings,
    list_campaign_activations,
    load_campaign_with_channels,
    resolve_channel_window_params,
    set_activation_running,
    upsert_agent_channel_settings,
)
from app.api.v1.campaigns import _get_campaign
from app.services.activation_cadence import resolve_channel_cadence_params
from app.services.capacity_service import (
    bind_outbound_capacity,
    release_outbound_capacity_for_lead,
    release_outbound_handle,
    try_acquire_outbound_capacity,
)
from worker.tasks.outbound_campaign import _resolve_recipient, _send_test_dispatch

router = APIRouter(tags=["activation"])


async def _get_agent(agent_id: uuid.UUID, user: User, db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    raise_if_cannot_view(agent, user, not_found_detail="Agent not found")
    return agent


def _validate_channel_type_param(channel_type: str) -> str:
    normalized = normalize_channel_type(channel_type)
    if normalized not in SUPPORTED_CHANNEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel type: {channel_type}",
        )
    return normalized


@router.get("/agents/{agent_id}/channel-settings", response_model=ChannelSettingsListResponse)
async def list_channel_settings(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelSettingsListResponse:
    agent = await _get_agent(agent_id, user, db)
    channels = await list_agent_channel_settings(agent, db)
    editable = not agent.is_system
    return ChannelSettingsListResponse(
        agent_id=agent.id,
        is_system=agent.is_system,
        editable=editable,
        channels=channels,
    )


@router.get(
    "/agents/{agent_id}/channel-settings/{channel_type}",
    response_model=ChannelSettingsResponse,
)
async def get_channel_settings(
    agent_id: uuid.UUID,
    channel_type: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelSettingsResponse:
    agent = await _get_agent(agent_id, user, db)
    normalized = _validate_channel_type_param(channel_type)
    row = await get_agent_channel_settings_row(db, agent.id, normalized)
    stored = row.params if row is not None else None
    return build_channel_settings_response(agent, normalized, stored)


@router.put(
    "/agents/{agent_id}/channel-settings/{channel_type}",
    response_model=ChannelSettingsResponse,
)
async def update_channel_settings(
    agent_id: uuid.UUID,
    channel_type: str,
    payload: ChannelSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelSettingsResponse:
    agent = await _get_agent(agent_id, user, db)
    raise_if_cannot_edit(agent, user)
    normalized = _validate_channel_type_param(channel_type)
    try:
        response = await upsert_agent_channel_settings(db, agent, normalized, payload.params)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return response


@router.get("/campaigns/{campaign_id}/activations", response_model=ActivationListResponse)
async def list_activations(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivationListResponse:
    campaign = await _get_campaign(campaign_id, user, db)
    activations = await list_campaign_activations(campaign, db)
    return ActivationListResponse(
        campaign_id=campaign.id,
        agent_id=campaign.agent_id,
        activations=activations,
    )


@router.post(
    "/campaigns/{campaign_id}/activations/{channel_type}/start",
    response_model=ActivationStartResponse,
)
async def start_activation(
    campaign_id: uuid.UUID,
    channel_type: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivationStartResponse:
    campaign = await _get_campaign(campaign_id, user, db)
    raise_if_cannot_edit(campaign, user)

    normalized = _validate_channel_type_param(channel_type)
    try:
        ensure_campaign_channel(campaign, normalized)
        ensure_active_agent(campaign)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    record = await set_activation_running(db, campaign, normalized, is_running=True)

    horario_inicio, horario_fim = await resolve_channel_window_params(
        db, campaign.agent_id, normalized
    )
    reason: str | None = None
    dispatched_now = 0
    if is_within_window(horario_inicio, horario_fim):
        dispatched_now = await dispatch_campaign_leads_for_channel(
            db, campaign, normalized, user.id
        )
    else:
        reason = outside_window_reason(horario_inicio, horario_fim)

    await db.commit()
    await db.refresh(record)

    activation = ActivationResponse(
        agent_id=record.agent_id,
        campaign_id=record.campaign_id,
        channel_type=record.channel_type,
        is_running=record.is_running,
        started_at=record.started_at,
        stopped_at=record.stopped_at,
    )
    return ActivationStartResponse(
        channel_type=normalized,
        leads_dispatched=dispatched_now,
        dispatched_now=dispatched_now,
        reason=reason,
        activation=activation,
    )


@router.post(
    "/campaigns/{campaign_id}/activations/{channel_type}/stop",
    response_model=ActivationResponse,
)
async def stop_activation(
    campaign_id: uuid.UUID,
    channel_type: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivationResponse:
    """
    Marca o canal como desligado. Tasks já enfileiradas no Redis/Celery não são canceladas.
    """
    campaign = await _get_campaign(campaign_id, user, db)
    raise_if_cannot_edit(campaign, user)

    normalized = _validate_channel_type_param(channel_type)
    try:
        ensure_campaign_channel(campaign, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    record = await set_activation_running(db, campaign, normalized, is_running=False)
    await db.commit()
    await db.refresh(record)

    return ActivationResponse(
        agent_id=record.agent_id,
        campaign_id=record.campaign_id,
        channel_type=record.channel_type,
        is_running=record.is_running,
        started_at=record.started_at,
        stopped_at=record.stopped_at,
    )


def _recipient_missing_message(channel: str) -> str:
    if channel in ("telegram", "video"):
        return f"Lead sem telegram_id para o canal {channel}"
    return f"Lead sem telefone para o canal {channel}"


async def _get_lead_for_test_dispatch(
    lead_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Lead:
    result = await db.execute(
        select(Lead)
        .options(
            selectinload(Lead.lead_base)
            .selectinload(LeadBase.campaign)
            .selectinload(Campaign.agent),
        )
        .where(Lead.id == lead_id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    raise_if_cannot_view(lead, user, not_found_detail="Lead not found")
    if lead.lead_base is None or lead.lead_base.campaign is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead has no campaign base configured",
        )
    return lead


@router.post("/activation/test-dispatch", response_model=TestDispatchResponse)
async def test_dispatch(
    payload: TestDispatchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestDispatchResponse:
    """
    Disparo ad-hoc síncrono para demonstração: um lead, um canal, agente escolhido.

    Usa a campanha da base do lead para LeadInteraction; bypassa janela/cadência/scheduler.
    """
    agent = await _get_agent(payload.agent_id, user, db)
    if agent.mode != AgentMode.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agente precisa ser ACTIVE para acionamento",
        )

    normalized = _validate_channel_type_param(payload.channel_type)
    lead = await _get_lead_for_test_dispatch(payload.lead_id, user, db)
    campaign = lead.lead_base.campaign

    recipient = _resolve_recipient(lead, normalized)
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_recipient_missing_message(normalized),
        )

    params = await resolve_channel_cadence_params(db, agent.id, normalized)
    capacity_handle = try_acquire_outbound_capacity(str(agent.id), normalized, params)
    if capacity_handle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Capacidade de atendimento cheia, tente novamente",
        )

    bound = False
    try:
        bind_outbound_capacity(str(lead.id), normalized, capacity_handle)
        bound = True

        dispatch_result = await _send_test_dispatch(
            db,
            lead,
            campaign,
            normalized,
            agent,
        )
        await db.commit()

        interaction_id: uuid.UUID | None = None
        interaction_result = await db.execute(
            select(LeadInteraction)
            .where(
                LeadInteraction.lead_id == lead.id,
                LeadInteraction.campaign_id == campaign.id,
                LeadInteraction.channel_type == normalized,
            )
            .order_by(LeadInteraction.created_at.desc())
            .limit(1)
        )
        interaction = interaction_result.scalar_one_or_none()
        if interaction is not None:
            interaction_id = interaction.id

        error_msg = dispatch_result.get("error")
        response_text = dispatch_result.get("response")
        if error_msg:
            return TestDispatchResponse(
                status="erro",
                channel=normalized,
                recipient=dispatch_result.get("recipient") or recipient,
                response=response_text,
                error=error_msg,
                lead_interaction_id=interaction_id,
            )

        return TestDispatchResponse(
            status="sucesso",
            channel=normalized,
            recipient=dispatch_result.get("recipient") or recipient,
            response=response_text,
            lead_interaction_id=interaction_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        return TestDispatchResponse(
            status="erro",
            channel=normalized,
            recipient=recipient,
            error=str(exc),
        )
    finally:
        if bound:
            release_outbound_capacity_for_lead(str(lead.id), normalized)
        else:
            release_outbound_handle(capacity_handle, str(lead.id), normalized)


@router.get("/activation/history", response_model=ActivationHistoryListResponse)
async def get_activation_history(
    skip: int = 0,
    limit: int = 50,
    campaign_id: uuid.UUID | None = None,
    channel_type: str | None = None,
    status: str | None = None,
    open_only: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivationHistoryListResponse:
    """
    Histórico paginado de acionamentos outbound (uma linha por LeadInteraction).

    Inclui todas as interações com ``data_acionamento`` preenchida — o mesmo lead/canal
    pode aparecer mais de uma vez se houver múltiplos registros.
    """
    if skip < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="skip must be >= 0")
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200",
        )

    normalized_channel: str | None = None
    if channel_type is not None and channel_type.strip():
        normalized_channel = _validate_channel_type_param(channel_type)

    normalized_status: str | None = None
    if status is not None and status.strip():
        normalized_status = status.strip().lower()
        if normalized_status not in HISTORY_STATUS_VALUES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of: {', '.join(HISTORY_STATUS_VALUES)}",
            )

    if campaign_id is not None:
        await _get_campaign(campaign_id, user, db)

    items, total = await list_activation_history(
        db,
        user,
        skip=skip,
        limit=limit,
        campaign_id=campaign_id,
        channel_type=normalized_channel,
        status_filter=normalized_status,
        open_only=open_only,
    )
    return ActivationHistoryListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post(
    "/activation/interactions/{interaction_id}/finalize",
    response_model=FinalizeInteractionResponse,
)
async def finalize_interaction(
    interaction_id: uuid.UUID,
    payload: FinalizeInteractionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FinalizeInteractionResponse:
    """Encerra manualmente uma LeadInteraction aberta (outbound), aplicando tabulação."""
    record = await get_lead_interaction_for_user(db, interaction_id, user)
    await validate_tabulacao_codigo_for_user(db, user, payload.tabulacao_codigo)
    response = await finalize_lead_interaction_manual(
        db,
        record,
        tabulacao_codigo=payload.tabulacao_codigo,
        status_interno=payload.status_interno,
    )
    await db.commit()
    return response
