"""Lead base API routes."""

from __future__ import annotations

import uuid
from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import raise_if_cannot_delete, raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.campaign import Campaign, CampaignChannel
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseChannel, LeadBaseSource
from app.models.user import User
from app.schemas.lead import LeadListResponse, LeadResponse
from app.schemas.lead_base import (
    DevolutivaFileResponse,
    LeadBaseColumnMappingUpdate,
    LeadBaseCreate,
    LeadBaseListResponse,
    LeadBaseResponse,
)
from app.schemas.metrics import MetricsResponse
from app.services.csv_import import build_column_mapping, parse_csv_content, row_to_lead_data
from app.services.devolutiva import (
    gerar_devolutiva_base,
    list_historical_devolutivas,
    read_historical_devolutiva,
)
from app.services.metrics import get_lead_base_metrics

router = APIRouter(prefix="/lead-bases", tags=["lead-bases"])


def _normalize_channel_types(channel_types: list[str]) -> list[str]:
    normalized = [channel_type.strip().lower() for channel_type in channel_types if channel_type.strip()]
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one channel type is required",
        )
    return normalized


async def _get_user_campaign(
    campaign_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Campaign:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


async def _validate_campaign_channels(
    campaign_id: uuid.UUID,
    channel_types: list[str],
    db: AsyncSession,
) -> None:
    result = await db.execute(
        select(CampaignChannel.channel_type).where(CampaignChannel.campaign_id == campaign_id)
    )
    allowed = {channel_type.lower() for channel_type in result.scalars().all()}
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign has no channels configured",
        )

    requested = set(channel_types)
    invalid = requested - allowed
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Channel types not in campaign: {', '.join(sorted(invalid))}",
        )


def _campaign_visibility_filter(user: User):
    return or_(Campaign.is_system.is_(True), Campaign.user_id == user.id)


async def _get_user_lead_base(
    lead_base_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> LeadBase:
    result = await db.execute(
        select(LeadBase)
        .options(
            selectinload(LeadBase.lead_base_channels),
            selectinload(LeadBase.campaign),
        )
        .join(Campaign)
        .where(LeadBase.id == lead_base_id, _campaign_visibility_filter(user))
    )
    lead_base = result.scalar_one_or_none()
    if lead_base is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead base not found")
    raise_if_cannot_view(lead_base, user, not_found_detail="Lead base not found")
    return lead_base


async def _count_leads_for_bases(
    db: AsyncSession,
    lead_base_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not lead_base_ids:
        return {}

    result = await db.execute(
        select(Lead.lead_base_id, func.count(Lead.id))
        .where(Lead.lead_base_id.in_(lead_base_ids))
        .group_by(Lead.lead_base_id)
    )
    return dict(result.all())


def _to_lead_base_response(lead_base: LeadBase, leads_count: int) -> LeadBaseResponse:
    return LeadBaseResponse(
        id=lead_base.id,
        campaign_id=lead_base.campaign_id,
        data_recebimento=lead_base.data_recebimento,
        data_inicio=lead_base.data_inicio,
        data_fim=lead_base.data_fim,
        column_mapping=lead_base.column_mapping,
        channel_types=[channel.channel_type for channel in lead_base.lead_base_channels],
        leads_count=leads_count,
        created_at=lead_base.created_at,
    )


async def _create_lead_base_record(
    *,
    campaign_id: uuid.UUID,
    data_recebimento: date,
    data_inicio: date | None,
    data_fim: date | None,
    column_mapping: dict[str, str],
    channel_types: list[str],
    source: LeadBaseSource,
    db: AsyncSession,
) -> LeadBase:
    lead_base = LeadBase(
        campaign_id=campaign_id,
        data_recebimento=data_recebimento,
        data_inicio=data_inicio,
        data_fim=data_fim,
        column_mapping=column_mapping,
        source=source,
    )
    db.add(lead_base)
    await db.flush()

    for channel_type in channel_types:
        db.add(LeadBaseChannel(lead_base_id=lead_base.id, channel_type=channel_type))

    await db.flush()
    await db.refresh(lead_base, attribute_names=["lead_base_channels"])
    return lead_base


@router.get("/", response_model=LeadBaseListResponse)
async def list_lead_bases(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadBaseListResponse:
    if skip < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="skip must be >= 0")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 200")

    total = await db.scalar(
        select(func.count())
        .select_from(LeadBase)
        .join(Campaign)
        .where(_campaign_visibility_filter(user))
    )

    result = await db.execute(
        select(LeadBase)
        .options(selectinload(LeadBase.lead_base_channels))
        .join(Campaign)
        .where(_campaign_visibility_filter(user))
        .order_by(LeadBase.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    lead_bases = list(result.scalars().unique().all())
    counts = await _count_leads_for_bases(db, [lead_base.id for lead_base in lead_bases])

    return LeadBaseListResponse(
        items=[
            _to_lead_base_response(lead_base, counts.get(lead_base.id, 0))
            for lead_base in lead_bases
        ],
        total=total or 0,
        skip=skip,
        limit=limit,
    )


@router.post("/", response_model=LeadBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_lead_base(
    payload: LeadBaseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadBaseResponse:
    await _get_user_campaign(payload.campaign_id, user, db)
    channel_types = _normalize_channel_types(payload.channel_types)
    await _validate_campaign_channels(payload.campaign_id, channel_types, db)

    lead_base = await _create_lead_base_record(
        campaign_id=payload.campaign_id,
        data_recebimento=payload.data_recebimento,
        data_inicio=payload.data_inicio,
        data_fim=payload.data_fim,
        column_mapping=payload.column_mapping,
        channel_types=channel_types,
        source=LeadBaseSource.MANUAL,
        db=db,
    )

    await db.commit()
    await db.refresh(lead_base, attribute_names=["lead_base_channels"])
    return _to_lead_base_response(lead_base, leads_count=0)


@router.delete("/{lead_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_base(
    lead_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    lead_base = await _get_user_lead_base(lead_base_id, user, db)
    raise_if_cannot_delete(lead_base, user)
    await db.delete(lead_base)
    await db.commit()


@router.post("/import", response_model=LeadBaseResponse, status_code=status.HTTP_201_CREATED)
async def import_lead_base_csv(
    campaign_id: uuid.UUID = Form(...),
    channel_types: list[str] = Form(...),
    data_recebimento: date = Form(...),
    data_inicio: date | None = Form(default=None),
    data_fim: date | None = Form(default=None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadBaseResponse:
    await _get_user_campaign(campaign_id, user, db)
    normalized_channels = _normalize_channel_types(channel_types)
    await _validate_campaign_channels(campaign_id, normalized_channels, db)

    raw_content = await file.read()
    try:
        content = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded",
        ) from exc

    headers, rows = parse_csv_content(content)
    if not headers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file is empty")

    index_to_field, column_mapping = build_column_mapping(headers)
    lead_base = await _create_lead_base_record(
        campaign_id=campaign_id,
        data_recebimento=data_recebimento,
        data_inicio=data_inicio,
        data_fim=data_fim,
        column_mapping=column_mapping,
        channel_types=normalized_channels,
        source=LeadBaseSource.IMPORT,
        db=db,
    )

    leads_to_insert: list[Lead] = []
    for row in rows:
        lead_data = row_to_lead_data(
            row,
            index_to_field,
            user_id=user.id,
            lead_base_id=lead_base.id,
        )
        if lead_data is None:
            continue
        leads_to_insert.append(Lead(**lead_data))

    if leads_to_insert:
        db.add_all(leads_to_insert)

    await db.commit()
    await db.refresh(lead_base, attribute_names=["lead_base_channels"])
    return _to_lead_base_response(lead_base, leads_count=len(leads_to_insert))


@router.patch("/{lead_base_id}/column-mapping", response_model=LeadBaseResponse)
async def update_lead_base_column_mapping(
    lead_base_id: uuid.UUID,
    payload: LeadBaseColumnMappingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadBaseResponse:
    lead_base = await _get_user_lead_base(lead_base_id, user, db)
    raise_if_cannot_edit(lead_base, user)
    lead_base.column_mapping = payload.column_mapping
    await db.commit()
    await db.refresh(lead_base, attribute_names=["lead_base_channels"])
    counts = await _count_leads_for_bases(db, [lead_base.id])
    return _to_lead_base_response(lead_base, counts.get(lead_base.id, 0))


@router.get("/{lead_base_id}/metrics", response_model=MetricsResponse)
async def lead_base_metrics(
    lead_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MetricsResponse:
    await _get_user_lead_base(lead_base_id, user, db)
    return await get_lead_base_metrics(db, lead_base_id)


@router.get("/{lead_base_id}/devolutiva")
async def download_devolutiva_on_demand(
    lead_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _get_user_lead_base(lead_base_id, user, db)
    xlsx_bytes = await gerar_devolutiva_base(db, lead_base_id)
    today = date.today().isoformat()
    filename = f"devolutiva_{lead_base_id}_{today}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lead_base_id}/devolutivas", response_model=list[DevolutivaFileResponse])
async def list_devolutiva_files(
    lead_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DevolutivaFileResponse]:
    await _get_user_lead_base(lead_base_id, user, db)
    files = list_historical_devolutivas(lead_base_id)
    return [DevolutivaFileResponse.model_validate(item) for item in files]


@router.get("/{lead_base_id}/devolutivas/{data}")
async def download_historical_devolutiva(
    lead_base_id: uuid.UUID,
    data: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _get_user_lead_base(lead_base_id, user, db)
    try:
        xlsx_bytes = read_historical_devolutiva(lead_base_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Devolutiva not found") from exc

    filename = f"devolutiva_{lead_base_id}_{data}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lead_base_id}/leads", response_model=LeadListResponse)
async def list_lead_base_leads(
    lead_base_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    if skip < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="skip must be >= 0")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 200")

    await _get_user_lead_base(lead_base_id, user, db)

    total = await db.scalar(
        select(func.count()).select_from(Lead).where(Lead.lead_base_id == lead_base_id)
    )

    result = await db.execute(
        select(Lead)
        .where(Lead.lead_base_id == lead_base_id)
        .order_by(Lead.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    leads = list(result.scalars().all())

    return LeadListResponse(
        items=[LeadResponse.model_validate(lead) for lead in leads],
        total=total or 0,
        skip=skip,
        limit=limit,
    )
