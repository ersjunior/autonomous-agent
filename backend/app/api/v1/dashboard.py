"""Dashboard home summary API."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activation_defaults import SUPPORTED_CHANNEL_TYPES, normalize_channel_type
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.dashboard import DashboardCampaignsResponse, DashboardSummaryResponse
from app.services.dashboard_metrics import get_dashboard_campaigns, get_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _validate_channel_type_param(channel_type: str) -> str:
    normalized = normalize_channel_type(channel_type)
    if normalized not in SUPPORTED_CHANNEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel type: {channel_type}",
        )
    return normalized


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    channel_type: str | None = Query(
        default=None,
        description="Filtra interações por canal (whatsapp, telegram, voice)",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Métricas agregadas para a home do dashboard (cards + gráficos)."""
    normalized_channel: str | None = None
    if channel_type is not None and channel_type.strip():
        normalized_channel = _validate_channel_type_param(channel_type)

    return await get_dashboard_summary(
        db,
        user_id=user.id,
        channel_type=normalized_channel,
    )


@router.get("/campaigns", response_model=DashboardCampaignsResponse)
async def dashboard_campaigns(
    channel_type: str | None = Query(
        default=None,
        description="Filtra métricas de interação por canal (whatsapp, telegram, voice)",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardCampaignsResponse:
    """Tabela rica de campanhas para a home do dashboard."""
    normalized_channel: str | None = None
    if channel_type is not None and channel_type.strip():
        normalized_channel = _validate_channel_type_param(channel_type)

    return await get_dashboard_campaigns(
        db,
        user_id=user.id,
        channel_type=normalized_channel,
    )
