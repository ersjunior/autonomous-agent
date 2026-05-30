"""Campaign CRUD API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.user import User
from app.schemas.campaign import (
    CampaignCreate,
    CampaignResponse,
    CampaignStartResponse,
    CampaignUpdate,
)
from worker.tasks.outbound_campaign import send_campaign_message

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def _get_campaign(
    campaign_id: uuid.UUID, user: User, db: AsyncSession
) -> Campaign:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


async def _get_user_agent(
    agent_id: uuid.UUID, user: User, db: AsyncSession
) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Campaign]:
    result = await db.execute(select(Campaign).where(Campaign.user_id == user.id))
    return list(result.scalars().all())


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    await _get_user_agent(payload.agent_id, user, db)
    campaign = Campaign(
        user_id=user.id,
        agent_id=payload.agent_id,
        name=payload.name,
        channel_type=payload.channel_type,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    return await _get_campaign(campaign_id, user, db)


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Campaign:
    campaign = await _get_campaign(campaign_id, user, db)
    data = payload.model_dump(exclude_unset=True)
    if "agent_id" in data:
        await _get_user_agent(data["agent_id"], user, db)
    for field, value in data.items():
        setattr(campaign, field, value)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/start", response_model=CampaignStartResponse)
async def start_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignStartResponse:
    campaign = await _get_campaign(campaign_id, user, db)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign cannot be started from status '{campaign.status}'",
        )

    result = await db.execute(
        select(Lead).where(Lead.user_id == user.id, Lead.status == "new")
    )
    leads = list(result.scalars().all())
    channel = campaign.channel_type.value.lower()

    for lead in leads:
        send_campaign_message.delay(str(lead.id), str(campaign.id), channel)

    campaign.status = "active"
    campaign.leads_count = len(leads)
    await db.commit()

    return CampaignStartResponse(status="started", leads_dispatched=len(leads))


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    campaign = await _get_campaign(campaign_id, user, db)
    await db.delete(campaign)
    await db.commit()
