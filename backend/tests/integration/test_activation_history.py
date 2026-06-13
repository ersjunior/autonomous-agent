"""Integração — activation_history: paginação, filtros, ownership, finalização manual."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign
from app.models.lead_interaction import LeadInteraction
from app.services.activation_history import (
    finalize_lead_interaction_manual,
    list_activation_history,
    validate_tabulacao_codigo_for_user,
)
from tests.integration.helpers import (
    OwnerContext,
    create_activation_records,
    create_lead_interaction,
    create_lead_on_base,
    create_owner_context,
    tabulacao_codigo_for,
)

pytestmark = pytest.mark.integration

BASE_TIME = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)


async def test_pagination_returns_correct_pages(owner_ctx: OwnerContext, db_session) -> None:
    await create_activation_records(db_session, owner_ctx, 7, base_time=BASE_TIME)

    page1, total = await list_activation_history(
        db_session, owner_ctx.user, skip=0, limit=3
    )
    page2, total2 = await list_activation_history(
        db_session, owner_ctx.user, skip=3, limit=3
    )

    assert total == total2 == 7
    assert len(page1) == 3
    assert len(page2) == 3

    timestamps = [item.data_acionamento for item in page1 + page2]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_excludes_li_without_data_acionamento(
    owner_ctx: OwnerContext, db_session
) -> None:
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="inbound", telefone="5511888777666"
    )
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=None,
        data_ultimo_contato=datetime.now(timezone.utc),
    )
    await create_activation_records(db_session, owner_ctx, 2, base_time=BASE_TIME)

    _, total = await list_activation_history(db_session, owner_ctx.user, skip=0, limit=50)

    assert total == 2


async def test_filter_by_campaign_id(owner_ctx: OwnerContext, db_session) -> None:
    other_campaign = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="Other Campaign",
        status="active",
    )
    db_session.add(other_campaign)
    await db_session.flush()

    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="other-camp", telefone="5511777666555"
    )
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=other_campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=BASE_TIME,
    )

    items, total = await list_activation_history(
        db_session,
        owner_ctx.user,
        skip=0,
        limit=50,
        campaign_id=owner_ctx.campaign.id,
    )

    assert total == 3
    assert all(item.campaign_id == owner_ctx.campaign.id for item in items)


async def test_filter_by_channel_type(owner_ctx: OwnerContext, db_session) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, channel_type="whatsapp"
    )
    await create_activation_records(
        db_session, owner_ctx, 3, base_time=BASE_TIME, channel_type="telegram"
    )

    items, total = await list_activation_history(
        db_session,
        owner_ctx.user,
        skip=0,
        limit=50,
        channel_type="telegram",
    )

    assert total == 3
    assert all(item.channel_type == "telegram" for item in items)


async def test_filter_by_status(owner_ctx: OwnerContext, db_session) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, status="convertido"
    )
    await create_activation_records(
        db_session, owner_ctx, 3, base_time=BASE_TIME, status="em_andamento"
    )

    _, total = await list_activation_history(
        db_session,
        owner_ctx.user,
        skip=0,
        limit=50,
        status_filter="convertido",
    )

    assert total == 2


async def test_filter_open_only_excludes_terminal(
    owner_ctx: OwnerContext, db_session
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, status="convertido"
    )
    await create_activation_records(
        db_session, owner_ctx, 4, base_time=BASE_TIME, status="em_andamento"
    )

    items, total = await list_activation_history(
        db_session,
        owner_ctx.user,
        skip=0,
        limit=50,
        open_only=True,
    )

    assert total == 4
    assert all(not item.is_terminal for item in items)


async def test_ownership_isolates_tenants(
    owner_ctx: OwnerContext, second_owner, db_session
) -> None:
    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)
    other_ctx = await create_owner_context(db_session, email_suffix="act-other")
    await create_activation_records(db_session, other_ctx, 2, base_time=BASE_TIME)

    owner_items, owner_total = await list_activation_history(
        db_session, owner_ctx.user, skip=0, limit=50
    )
    other_items, other_total = await list_activation_history(
        db_session, other_ctx.user, skip=0, limit=50
    )
    second_items, second_total = await list_activation_history(
        db_session, second_owner, skip=0, limit=50
    )

    assert owner_total == 3
    assert other_total == 2
    assert second_total == 0
    owner_ids = {item.id for item in owner_items}
    other_ids = {item.id for item in other_items}
    assert owner_ids.isdisjoint(other_ids)


async def test_finalize_manual_applies_tabulacao_and_closes(
    owner_ctx: OwnerContext,
    db_session,
    mock_capacity_release,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.activation_history.is_in_human_mode", lambda _c, _u: False
    )
    records = await create_activation_records(
        db_session, owner_ctx, 1, base_time=BASE_TIME, status="em_andamento"
    )
    record = records[0]
    loaded = await db_session.execute(
        select(LeadInteraction)
        .options(
            selectinload(LeadInteraction.lead),
            selectinload(LeadInteraction.campaign),
        )
        .where(LeadInteraction.id == record.id)
    )
    record = loaded.scalar_one()

    result = await finalize_lead_interaction_manual(
        db_session, record, tabulacao_codigo="NEG:SUCESSO"
    )

    assert result.ok is True
    assert result.status == "convertido"
    assert result.tabulacao_codigo == "NEG:SUCESSO"
    assert record.status == "convertido"
    assert await tabulacao_codigo_for(db_session, record) == "NEG:SUCESSO"
    assert record.tabulacao_origem == "MANUAL_FINALIZE"
    assert len(mock_capacity_release["outbound_calls"]) == 1

    open_items, open_total = await list_activation_history(
        db_session, owner_ctx.user, skip=0, limit=50, open_only=True
    )
    assert open_total == 0
    assert all(item.id != record.id for item in open_items)


async def test_finalize_invalid_tabulacao_raises(
    owner_ctx: OwnerContext, db_session
) -> None:
    with pytest.raises(HTTPException) as exc:
        await validate_tabulacao_codigo_for_user(
            db_session, owner_ctx.user, "NEG:INEXISTENTE"
        )
    assert exc.value.status_code == 400


async def test_finalize_already_terminal_raises(
    owner_ctx: OwnerContext, db_session, mock_capacity_release, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.services.activation_history.is_in_human_mode", lambda _c, _u: False
    )
    records = await create_activation_records(
        db_session, owner_ctx, 1, base_time=BASE_TIME, status="convertido"
    )
    record = records[0]

    with pytest.raises(HTTPException) as exc:
        await finalize_lead_interaction_manual(
            db_session, record, tabulacao_codigo="NEG:SUCESSO"
        )
    assert exc.value.status_code == 400
    assert "encerrado" in exc.value.detail.lower()
