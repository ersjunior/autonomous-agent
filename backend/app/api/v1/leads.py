"""Lead CRUD API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.lead import Lead
from app.models.user import User
from app.schemas.lead import LeadCreate, LeadResponse, LeadUpdate

router = APIRouter(prefix="/leads", tags=["leads"])


async def _get_lead(
    lead_id: uuid.UUID, user: User, db: AsyncSession
) -> Lead:
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


@router.get("/", response_model=list[LeadResponse])
async def list_leads(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Lead]:
    result = await db.execute(select(Lead).where(Lead.user_id == user.id))
    return list(result.scalars().all())


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    lead = Lead(
        user_id=user.id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        extra_data=payload.extra_data,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    return await _get_lead(lead_id, user, db)


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    lead = await _get_lead(lead_id, user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    await db.commit()
    await db.refresh(lead)
    return lead


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    lead = await _get_lead(lead_id, user, db)
    await db.delete(lead)
    await db.commit()
