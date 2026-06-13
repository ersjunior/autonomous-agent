"""API — status do túnel Cloudflare e webhooks (TUN-3)."""

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.tunnel import TunnelStatusResponse
from app.services.tunnel_status import get_tunnel_status

router = APIRouter(prefix="/tunnel", tags=["tunnel"])


@router.get("/status", response_model=TunnelStatusResponse)
async def read_tunnel_status(
    user: User = Depends(get_current_user),
) -> TunnelStatusResponse:
    """URL pública, modos, webhooks e health probe — somente leitura."""
    del user
    return await get_tunnel_status(run_probe=True)
