"""API — capacidade estimada e Erlang C (R-C)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.capacity import CapacityResponse
from app.services.capacity_analysis import get_capacity_analysis

router = APIRouter(prefix="/capacity", tags=["capacity"])


@router.get("", response_model=CapacityResponse)
async def get_capacity(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CapacityResponse:
    """Recursos, capacidade estimada, uso global (ativo+receptivo) e Erlang C."""
    del user
    return await get_capacity_analysis(db)
