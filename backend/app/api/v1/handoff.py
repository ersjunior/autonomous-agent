"""API — modo humano (handoff B-2)."""

from datetime import datetime

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.handoff import (
    HandoffContact,
    HandoffReactivateRequest,
    HandoffReactivateResponse,
)
from app.services.human_handoff import exit_human_mode, list_active_human_mode_contacts

router = APIRouter(prefix="/handoff", tags=["handoff"])


@router.get("/active", response_model=list[HandoffContact])
async def list_active_handoffs(
    user: User = Depends(get_current_user),
) -> list[HandoffContact]:
    """Contatos aguardando atendente humano (chaves human_mode:* no Redis)."""
    del user
    rows = list_active_human_mode_contacts()
    return [
        HandoffContact(
            channel=row["channel"],
            user_id=row["user_id"],
            escalated_at=(
                datetime.fromisoformat(row["escalated_at"])
                if row.get("escalated_at")
                else None
            ),
            ttl_seconds=row.get("ttl_seconds"),
        )
        for row in rows
    ]


@router.post("/reactivate", response_model=HandoffReactivateResponse)
async def reactivate_from_human_mode(
    payload: HandoffReactivateRequest,
    user: User = Depends(get_current_user),
) -> HandoffReactivateResponse:
    """Operador devolve o contato ao bot (remove modo humano)."""
    del user
    reactivated = exit_human_mode(payload.channel, payload.user_id)
    return HandoffReactivateResponse(
        reactivated=reactivated,
        channel=payload.channel,
        user_id=payload.user_id,
    )
