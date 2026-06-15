"""Integração — finalização terminal de chamada de voz."""

from __future__ import annotations

import pytest

from app.models.lead_interaction import LeadInteraction
from app.services.voice_call_finalize import finalize_voice_call_terminal
from tests.integration.helpers import OwnerContext, tabulacao_codigo_for

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_finalize_voice_call_terminal_applies_ausente(
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
) -> None:
    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="voice",
        status="em_andamento",
        lifecycle_version=1,
        twilio_call_sid="CA-finalize-test",
    )
    db_session.add(li)
    await db_session.flush()

    ok = await finalize_voice_call_terminal(
        db_session,
        call_sid="CA-finalize-test",
        from_number=owner_ctx.lead.telefone_1,
        origem="VOICE_SILENCE",
    )
    assert ok is True
    await db_session.refresh(li)
    assert li.status == "nao_atendido"
    assert await tabulacao_codigo_for(db_session, li) == "NEG:AUSENTE"


@pytest.mark.asyncio
async def test_finalize_voice_call_terminal_idempotent(
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
) -> None:
    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="voice",
        status="convertido",
        lifecycle_version=1,
        twilio_call_sid="CA-already-done",
    )
    db_session.add(li)
    await db_session.flush()

    ok = await finalize_voice_call_terminal(
        db_session,
        call_sid="CA-already-done",
        from_number=owner_ctx.lead.telefone_1,
    )
    assert ok is False
    await db_session.refresh(li)
    assert li.status == "convertido"
