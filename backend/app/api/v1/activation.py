"""Agent channel settings and campaign activation (motor Layer A)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activation_defaults import (
    SUPPORTED_CHANNEL_TYPES,
    normalize_channel_type,
)
from app.core.authorization import raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent import Agent
from app.models.user import User
from app.schemas.activation import (
    ActivationListResponse,
    ActivationResponse,
    ActivationStartResponse,
    ChannelSettingsListResponse,
    ChannelSettingsResponse,
    ChannelSettingsUpdate,
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
