"""Lead CRUD API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import (
    raise_if_cannot_delete_lead,
    raise_if_cannot_edit_lead,
    raise_if_cannot_view,
)
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
from app.models.user import User
from app.schemas.lead import LeadCreate, LeadResponse, LeadUpdate

router = APIRouter(prefix="/leads", tags=["leads"])


async def _get_lead(
    lead_id: uuid.UUID, user: User, db: AsyncSession
) -> Lead:
    result = await db.execute(
        select(Lead)
        .options(selectinload(Lead.lead_base))
        .where(Lead.id == lead_id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    raise_if_cannot_view(lead, user, not_found_detail="Lead not found")
    return lead


async def _get_user_lead_base(
    lead_base_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> LeadBase:
    result = await db.execute(
        select(LeadBase)
        .options(selectinload(LeadBase.lead_base_channels))
        .join(Campaign)
        .where(LeadBase.id == lead_base_id, Campaign.user_id == user.id)
    )
    lead_base = result.scalar_one_or_none()
    if lead_base is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead base not found")
    if lead_base.source == LeadBaseSource.IMPORT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add leads individually to an imported base",
        )
    return lead_base


@router.get("/", response_model=list[LeadResponse])
async def list_leads(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Lead]:
    result = await db.execute(
        select(Lead).where(or_(Lead.is_system.is_(True), Lead.user_id == user.id))
    )
    return list(result.scalars().all())


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Lead:
    await _get_user_lead_base(payload.lead_base_id, user, db)

    lead = Lead(
        user_id=user.id,
        lead_base_id=payload.lead_base_id,
        id_cliente=payload.id_cliente,
        nome_cliente=payload.nome_cliente,
        cpf_cliente=payload.cpf_cliente,
        email_cliente=payload.email_cliente,
        telefone_1=payload.telefone_1,
        telefone_2=payload.telefone_2,
        telefone_3=payload.telefone_3,
        aux_values=payload.aux_values,
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
    raise_if_cannot_edit_lead(lead, user)
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
    raise_if_cannot_delete_lead(lead, user)
    await db.delete(lead)
    await db.commit()
