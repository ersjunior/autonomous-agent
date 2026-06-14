"""Business logic for channel settings merge and campaign activations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activation_defaults import (
    SUPPORTED_CHANNEL_TYPES,
    channel_family,
    default_params_for_channel,
    normalize_channel_type,
)
from app.models.agent import Agent, AgentMode
from app.models.agent_activation import AgentActivation
from app.models.agent_channel_settings import AgentChannelSettings
from app.models.campaign import Campaign, CampaignChannel
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseChannel
from app.models.lead_interaction import LeadInteraction
from app.schemas.activation import (
    ActivationResponse,
    ChannelSettingsResponse,
    MessagingParams,
    VoiceVideoParams,
)
from worker.tasks.outbound_campaign import send_campaign_message

SETTINGS_CHANNEL_TYPES = sorted(SUPPORTED_CHANNEL_TYPES)


def validate_params_for_channel(channel_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize params JSON for the channel family."""
    family = channel_family(channel_type)
    if family == "voice":
        model = VoiceVideoParams.model_validate(params)
    else:
        model = MessagingParams.model_validate(params)
    return model.model_dump()


def merged_params(
    channel_type: str,
    stored: dict[str, Any] | None,
) -> dict[str, Any]:
    base = default_params_for_channel(channel_type)
    if stored:
        base.update(stored)
    return base


async def get_agent_channel_settings_row(
    db: AsyncSession,
    agent_id: uuid.UUID,
    channel_type: str,
) -> AgentChannelSettings | None:
    normalized = normalize_channel_type(channel_type)
    result = await db.execute(
        select(AgentChannelSettings).where(
            AgentChannelSettings.agent_id == agent_id,
            AgentChannelSettings.channel_type == normalized,
        )
    )
    return result.scalar_one_or_none()


def build_channel_settings_response(
    agent: Agent,
    channel_type: str,
    stored: dict[str, Any] | None,
) -> ChannelSettingsResponse:
    normalized = normalize_channel_type(channel_type)
    editable = not agent.is_system
    return ChannelSettingsResponse(
        agent_id=agent.id,
        channel_type=normalized,
        params=merged_params(normalized, stored),
        is_system=agent.is_system,
        editable=editable,
    )


async def list_agent_channel_settings(
    agent: Agent,
    db: AsyncSession,
) -> list[ChannelSettingsResponse]:
    result = await db.execute(
        select(AgentChannelSettings).where(AgentChannelSettings.agent_id == agent.id)
    )
    rows = {row.channel_type: row.params for row in result.scalars().all()}
    return [
        build_channel_settings_response(agent, ch, rows.get(ch))
        for ch in SETTINGS_CHANNEL_TYPES
    ]


async def upsert_agent_channel_settings(
    db: AsyncSession,
    agent: Agent,
    channel_type: str,
    params: dict[str, Any],
) -> ChannelSettingsResponse:
    normalized = normalize_channel_type(channel_type)
    validated = validate_params_for_channel(normalized, params)
    row = await get_agent_channel_settings_row(db, agent.id, normalized)
    now = datetime.now(timezone.utc)
    if row is None:
        row = AgentChannelSettings(
            agent_id=agent.id,
            channel_type=normalized,
            params=validated,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.params = validated
        row.updated_at = now
    await db.flush()
    return build_channel_settings_response(agent, normalized, validated)


async def get_activation_map(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> dict[str, AgentActivation]:
    result = await db.execute(
        select(AgentActivation).where(AgentActivation.campaign_id == campaign_id)
    )
    return {row.channel_type: row for row in result.scalars().all()}


def activation_to_response(
    campaign: Campaign,
    channel_type: str,
    record: AgentActivation | None,
) -> ActivationResponse:
    normalized = normalize_channel_type(channel_type)
    if record is None:
        return ActivationResponse(
            agent_id=campaign.agent_id,
            campaign_id=campaign.id,
            channel_type=normalized,
            is_running=False,
            started_at=None,
            stopped_at=None,
        )
    return ActivationResponse(
        agent_id=record.agent_id,
        campaign_id=record.campaign_id,
        channel_type=record.channel_type,
        is_running=record.is_running,
        started_at=record.started_at,
        stopped_at=record.stopped_at,
    )


async def list_campaign_activations(
    campaign: Campaign,
    db: AsyncSession,
) -> list[ActivationResponse]:
    activation_map = await get_activation_map(db, campaign.id)
    channel_types = [ch.channel_type for ch in campaign.campaign_channels]
    return [
        activation_to_response(campaign, ch, activation_map.get(normalize_channel_type(ch)))
        for ch in channel_types
    ]


async def set_activation_running(
    db: AsyncSession,
    campaign: Campaign,
    channel_type: str,
    *,
    is_running: bool,
) -> AgentActivation:
    normalized = normalize_channel_type(channel_type)
    now = datetime.now(timezone.utc)
    activation_map = await get_activation_map(db, campaign.id)
    record = activation_map.get(normalized)
    if record is None:
        record = AgentActivation(
            agent_id=campaign.agent_id,
            campaign_id=campaign.id,
            channel_type=normalized,
            is_running=is_running,
            started_at=now if is_running else None,
            stopped_at=None if is_running else now,
            updated_at=now,
        )
        db.add(record)
    else:
        record.agent_id = campaign.agent_id
        record.is_running = is_running
        record.updated_at = now
        if is_running:
            record.started_at = now
            record.stopped_at = None
        else:
            record.stopped_at = now
    await db.flush()
    return record


async def set_all_campaign_activations_running(
    db: AsyncSession,
    campaign: Campaign,
    *,
    is_running: bool,
) -> None:
    for ch in campaign.campaign_channels:
        await set_activation_running(db, campaign, ch.channel_type, is_running=is_running)


async def resolve_channel_window_params(
    db: AsyncSession,
    agent_id: uuid.UUID,
    channel_type: str,
) -> tuple[str, str]:
    """Resolve horario_inicio/fim for (agent, channel) — DB row merged with system defaults."""
    row = await get_agent_channel_settings_row(db, agent_id, channel_type)
    stored = row.params if row else None
    params = merged_params(channel_type, stored)
    return params["horario_inicio"], params["horario_fim"]


async def get_pending_leads_for_channel(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    channel_type: str,
    *,
    user_id: uuid.UUID | None = None,
) -> list[Lead]:
    """
    Leads da campanha com o canal na base e sem LeadInteraction para (lead, campaign, channel).
    """
    normalized = normalize_channel_type(channel_type)
    interaction_exists = (
        select(LeadInteraction.id)
        .where(
            LeadInteraction.lead_id == Lead.id,
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == normalized,
        )
        .correlate(Lead)
        .exists()
    )
    stmt = (
        select(Lead)
        .join(LeadBase, Lead.lead_base_id == LeadBase.id)
        .join(LeadBaseChannel, LeadBaseChannel.lead_base_id == LeadBase.id)
        .where(
            LeadBase.campaign_id == campaign_id,
            LeadBaseChannel.channel_type == normalized,
            ~interaction_exists,
        )
    )
    if user_id is not None:
        stmt = stmt.where(Lead.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


def lead_has_channel(lead: Lead, channel_type: str) -> bool:
    if lead.lead_base is None or not lead.lead_base.lead_base_channels:
        return False
    normalized = normalize_channel_type(channel_type)
    return any(
        normalize_channel_type(bc.channel_type) == normalized
        for bc in lead.lead_base.lead_base_channels
    )


async def dispatch_campaign_leads_for_channel(
    db: AsyncSession,
    campaign: Campaign,
    channel_type: str,
    user_id: uuid.UUID,
) -> int:
    """Enqueue outbound tasks for pending (not yet activated) leads on the given channel."""
    normalized = normalize_channel_type(channel_type)
    pending = await get_pending_leads_for_channel(
        db, campaign.id, normalized, user_id=user_id
    )
    dispatched = 0
    for lead in pending:
        send_campaign_message.delay(str(lead.id), str(campaign.id), normalized)
        dispatched += 1
    return dispatched


async def load_campaign_with_channels(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> Campaign | None:
    result = await db.execute(
        select(Campaign)
        .options(
            selectinload(Campaign.campaign_channels),
            selectinload(Campaign.agent),
        )
        .where(Campaign.id == campaign_id)
    )
    return result.scalar_one_or_none()


def ensure_campaign_channel(campaign: Campaign, channel_type: str) -> str:
    normalized = normalize_channel_type(channel_type)
    allowed = {normalize_channel_type(ch.channel_type) for ch in campaign.campaign_channels}
    if normalized not in allowed:
        raise ValueError(f"Channel type '{channel_type}' is not configured on this campaign")
    return normalized


def ensure_active_agent(campaign: Campaign) -> None:
    if campaign.agent is None:
        raise ValueError("Campaign has no agent")
    if campaign.agent.mode != AgentMode.ACTIVE:
        raise ValueError(
            f"Campaign agent must be ACTIVE for outbound activation (got {campaign.agent.mode.value})"
        )
