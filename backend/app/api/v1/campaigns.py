"""Campaign CRUD API routes."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import can_view, raise_if_cannot_delete, raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign, CampaignChannel
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.user import User
from app.schemas.campaign import (
    CampaignCreate,
    CampaignResponse,
    CampaignStartResponse,
    CampaignStopResponse,
    CampaignUpdate,
)
from app.schemas.metrics import MetricsResponse
from app.services.activation_service import set_all_campaign_activations_running
from app.services.metrics import get_campaign_metrics
from worker.tasks.outbound_campaign import send_campaign_message

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
logger = logging.getLogger(__name__)


def _normalize_channel_types(channel_types: list[str]) -> list[str]:
    normalized = [channel_type.strip().lower() for channel_type in channel_types if channel_type.strip()]
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one channel type is required",
        )
    return normalized


def _to_campaign_response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=campaign.id,
        agent_id=campaign.agent_id,
        name=campaign.name,
        status=campaign.status,
        channel_types=[channel.channel_type for channel in campaign.campaign_channels],
        leads_count=campaign.leads_count,
        is_system=campaign.is_system,
        created_at=campaign.created_at,
    )


async def _get_campaign(
    campaign_id: uuid.UUID, user: User, db: AsyncSession
) -> Campaign:
    result = await db.execute(
        select(Campaign)
        .options(
            selectinload(Campaign.campaign_channels),
            selectinload(Campaign.agent),
        )
        .where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    raise_if_cannot_view(campaign, user, not_found_detail="Campaign not found")
    return campaign


async def _get_agent_for_reference(
    agent_id: uuid.UUID, user: User, db: AsyncSession
) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None or not can_view(agent, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.mode == AgentMode.RECEPTIVE:
        logger.warning(
            "Campaign references RECEPTIVE agent %s (%s); outbound dispatch will be blocked",
            agent.id,
            agent.name,
        )
    return agent


async def _set_campaign_channels(
    campaign: Campaign,
    channel_types: list[str],
    db: AsyncSession,
) -> None:
    await db.execute(
        delete(CampaignChannel).where(CampaignChannel.campaign_id == campaign.id)
    )
    for channel_type in channel_types:
        db.add(CampaignChannel(campaign_id=campaign.id, channel_type=channel_type))
    await db.flush()


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignResponse]:
    result = await db.execute(
        select(Campaign)
        .options(selectinload(Campaign.campaign_channels))
        .where(or_(Campaign.is_system.is_(True), Campaign.user_id == user.id))
    )
    campaigns = list(result.scalars().unique().all())
    return [_to_campaign_response(campaign) for campaign in campaigns]


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    await _get_agent_for_reference(payload.agent_id, user, db)
    channel_types = _normalize_channel_types(payload.channel_types)

    campaign = Campaign(
        user_id=user.id,
        agent_id=payload.agent_id,
        name=payload.name,
    )
    db.add(campaign)
    await db.flush()
    await _set_campaign_channels(campaign, channel_types, db)

    await db.commit()
    await db.refresh(campaign, attribute_names=["campaign_channels"])
    return _to_campaign_response(campaign)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    campaign = await _get_campaign(campaign_id, user, db)
    return _to_campaign_response(campaign)


@router.get("/{campaign_id}/metrics", response_model=MetricsResponse)
async def campaign_metrics(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MetricsResponse:
    await _get_campaign(campaign_id, user, db)
    return await get_campaign_metrics(db, campaign_id)


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    campaign = await _get_campaign(campaign_id, user, db)
    raise_if_cannot_edit(campaign, user)
    data = payload.model_dump(exclude_unset=True)

    channel_types = data.pop("channel_types", None)
    if "agent_id" in data:
        await _get_agent_for_reference(data["agent_id"], user, db)

    for field, value in data.items():
        setattr(campaign, field, value)

    if channel_types is not None:
        await _set_campaign_channels(campaign, _normalize_channel_types(channel_types), db)

    await db.commit()
    await db.refresh(campaign, attribute_names=["campaign_channels"])
    return _to_campaign_response(campaign)


@router.post("/{campaign_id}/start", response_model=CampaignStartResponse)
async def start_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignStartResponse:
    campaign = await _get_campaign(campaign_id, user, db)
    raise_if_cannot_edit(campaign, user)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign cannot be started from status '{campaign.status}'",
        )

    if not campaign.campaign_channels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign has no channels configured",
        )

    result = await db.execute(
        select(Lead)
        .options(selectinload(Lead.lead_base).selectinload(LeadBase.lead_base_channels))
        .join(LeadBase)
        .where(LeadBase.campaign_id == campaign.id, Lead.user_id == user.id)
    )
    leads = list(result.scalars().unique().all())

    dispatched = 0
    for lead in leads:
        if not lead.lead_base or not lead.lead_base.lead_base_channels:
            continue
        send_campaign_message.delay(str(lead.id), str(campaign.id))
        dispatched += 1

    await set_all_campaign_activations_running(db, campaign, is_running=True)
    campaign.status = "active"
    campaign.leads_count = dispatched
    await db.commit()

    return CampaignStartResponse(status="started", leads_dispatched=dispatched)


@router.post("/{campaign_id}/stop", response_model=CampaignStopResponse)
async def stop_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignStopResponse:
    campaign = await _get_campaign(campaign_id, user, db)
    raise_if_cannot_edit(campaign, user)

    if campaign.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign cannot be stopped from status '{campaign.status}'",
        )

    channel_count = len(campaign.campaign_channels)
    await set_all_campaign_activations_running(db, campaign, is_running=False)
    campaign.status = "paused"
    await db.commit()

    return CampaignStopResponse(status="paused", activations_stopped=channel_count)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    campaign = await _get_campaign(campaign_id, user, db)
    raise_if_cannot_delete(campaign, user)
    await db.delete(campaign)
    await db.commit()
