"""Finalização terminal de chamadas de voz inbound (silêncio ou StatusCallback)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_interaction import LeadInteraction
from app.services.activation_slots import release_slot_for_lead
from app.services.capacity_service import (
    release_outbound_capacity_for_lead,
    release_receptive_capacity_for_lead,
)
from app.services.tabulacao_assignment import apply_tabulacao
from worker.tasks.conversation_routing import TERMINAL_STATUSES
from worker.tasks.lead_tracking import find_lead_by_channel_user, upsert_lead_interaction

logger = logging.getLogger(__name__)

VOICE_TERMINAL_TABULACAO = "NEG:AUSENTE"
VOICE_FAREWELL_TABULACAO = "NEG:SUCESSO"
VOICE_FAREWELL_ORIGEM = "VOICE_FAREWELL"


def _terminal_outcome_for_origem(origem: str) -> tuple[str, str]:
    if origem == VOICE_FAREWELL_ORIGEM:
        return "convertido", VOICE_FAREWELL_TABULACAO
    return "nao_atendido", VOICE_TERMINAL_TABULACAO


async def find_lead_interaction_for_voice_call(
    session: AsyncSession,
    *,
    call_sid: str | None = None,
    from_number: str | None = None,
) -> LeadInteraction | None:
    sid = (call_sid or "").strip()
    if sid:
        result = await session.execute(
            select(LeadInteraction)
            .where(
                LeadInteraction.twilio_call_sid == sid,
                LeadInteraction.channel_type == "voice",
            )
            .order_by(LeadInteraction.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is not None:
            return record

    phone = (from_number or "").strip()
    if not phone:
        return None

    lead = await find_lead_by_channel_user(session, "voice", phone)
    if lead is None or lead.lead_base is None:
        return None

    from worker.tasks.conversation_routing import get_latest_lead_interaction

    return await get_latest_lead_interaction(session, lead.id, "voice")


async def finalize_voice_call_terminal(
    session: AsyncSession,
    *,
    call_sid: str | None = None,
    from_number: str | None = None,
    origem: str = "VOICE_TERMINAL",
) -> bool:
    """
    Finaliza LI terminal conforme origem (silêncio → ausente; despedida → sucesso).

    Retorna True se transicionou para terminal nesta chamada.
    """
    record = await find_lead_interaction_for_voice_call(
        session,
        call_sid=call_sid,
        from_number=from_number,
    )

    phone = (from_number or "").strip()
    sid = (call_sid or "").strip()

    if record is None and phone:
        lead = await find_lead_by_channel_user(session, "voice", phone)
        if lead is not None and lead.lead_base is not None:
            record = await upsert_lead_interaction(
                session,
                lead.id,
                lead.lead_base.campaign_id,
                "voice",
                twilio_call_sid=sid or None,
            )

    if record is None:
        logger.info(
            "finalize_voice_call_terminal: sem LI call_sid=%s from=%s",
            call_sid,
            from_number,
        )
        return False

    if sid and not record.twilio_call_sid:
        record.twilio_call_sid = sid

    current = (record.status or "").lower()
    if current in TERMINAL_STATUSES:
        logger.debug(
            "finalize_voice_call_terminal: LI %s já terminal (%s)",
            record.id,
            current,
        )
        return False

    status_interno, tabulacao = _terminal_outcome_for_origem(origem)
    record.status = status_interno
    await apply_tabulacao(
        session,
        record,
        status_interno=status_interno,
        channel="voice",
        tabulacao_codigo=tabulacao,
        origem=origem,
    )
    release_slot_for_lead(str(record.lead_id), "voice")
    release_receptive_capacity_for_lead(str(record.lead_id), "voice")
    release_outbound_capacity_for_lead(str(record.lead_id), "voice")
    await session.flush()

    logger.info(
        "Chamada voz finalizada LI=%s call_sid=%s origem=%s",
        record.id,
        sid or record.twilio_call_sid,
        origem,
    )
    return True
