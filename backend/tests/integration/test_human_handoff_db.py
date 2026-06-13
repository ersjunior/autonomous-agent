"""Integração — handoff humano H-2: DB + Redis real."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.lead_interaction import LeadInteraction
from app.services.human_handoff import (
    assume_human_mode,
    enter_human_mode,
    finalize_handoff_lead,
    get_human_mode_payload,
    is_assumed,
    is_in_human_mode,
    sweep_human_handoff_timeouts,
)
from tests.integration.helpers import (
    OwnerContext,
    set_human_mode_timestamps,
    tabulacao_codigo_for,
)

pytestmark = pytest.mark.integration

OLD_TS = "2000-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_finalize_handoff_lead_applies_tabulacao_and_clears_redis(
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
    clean_redis,
):
    """Lead em modo humano → finalize NEG:SUCESSO → convertido + Redis limpo."""
    phone = owner_ctx.lead.telefone_1
    channel = "whatsapp"
    enter_human_mode(channel, phone, intent="escalate")
    assert is_in_human_mode(channel, phone)

    ok = await finalize_handoff_lead(
        db_session,
        channel=channel,
        user_id=phone,
        tabulacao_codigo="NEG:SUCESSO",
        origem="HANDOFF_FINALIZE",
    )

    assert ok is True
    assert not is_in_human_mode(channel, phone)

    result = await db_session.execute(
        select(LeadInteraction).where(
            LeadInteraction.lead_id == owner_ctx.lead.id,
            LeadInteraction.campaign_id == owner_ctx.campaign.id,
            LeadInteraction.channel_type == channel,
        )
    )
    li = result.scalar_one()
    assert li.status == "convertido"
    assert li.tabulacao_origem == "HANDOFF_FINALIZE"
    assert await tabulacao_codigo_for(db_session, li) == "NEG:SUCESSO"


@pytest.mark.asyncio
async def test_assume_human_mode_sets_assumed_at(
    owner_ctx: OwnerContext,
    clean_redis,
):
    """Escalar → assumir → is_assumed True + human_assumed_at no Redis."""
    phone = owner_ctx.lead.telefone_1
    channel = "whatsapp"
    enter_human_mode(channel, phone, intent="escalate")
    assert is_in_human_mode(channel, phone)
    assert not is_assumed(channel, phone)

    assert assume_human_mode(channel, phone, assumed_by="operator@test") is True
    assert is_assumed(channel, phone)

    payload = get_human_mode_payload(channel, phone)
    assert payload is not None
    assert payload.get("human_assumed_at")
    assert payload.get("assumed_by") == "operator@test"


@pytest.mark.asyncio
async def test_sweep_queue_timeout_returns_to_bot_without_db_terminal(
    db_session,
    clean_redis,
):
    """Não assumido + escalated_at antigo → sweep devolve ao bot (sem LI terminal)."""
    channel = "telegram"
    uid = f"sweep-q-{uuid.uuid4().hex[:8]}"
    enter_human_mode(channel, uid, intent="escalate")
    set_human_mode_timestamps(channel, uid, escalated_at=OLD_TS)

    before_count = (
        await db_session.execute(select(func.count()).select_from(LeadInteraction))
    ).scalar_one()

    stats = await sweep_human_handoff_timeouts(db_session)

    assert stats["returned_to_bot"] >= 1
    assert not is_in_human_mode(channel, uid)

    after_count = (
        await db_session.execute(select(func.count()).select_from(LeadInteraction))
    ).scalar_one()
    assert after_count == before_count


@pytest.mark.asyncio
async def test_sweep_assumed_timeout_auto_finalizes_abandono(
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
    clean_redis,
):
    """Assumido + human_assumed_at antigo → nao_atendido + NEG:ABANDONO + Redis limpo."""
    phone = owner_ctx.lead.telefone_1
    channel = "whatsapp"
    enter_human_mode(channel, phone, intent="escalate")
    assume_human_mode(channel, phone, assumed_by="timeout-test")
    set_human_mode_timestamps(channel, phone, human_assumed_at=OLD_TS)

    stats = await sweep_human_handoff_timeouts(db_session)

    assert stats["auto_finalized"] >= 1
    assert not is_in_human_mode(channel, phone)

    result = await db_session.execute(
        select(LeadInteraction).where(
            LeadInteraction.lead_id == owner_ctx.lead.id,
            LeadInteraction.channel_type == channel,
        )
    )
    li = result.scalar_one()
    assert li.status == "nao_atendido"
    assert li.tabulacao_origem == "HANDOFF_TIMEOUT"
    assert await tabulacao_codigo_for(db_session, li) == "NEG:ABANDONO"
