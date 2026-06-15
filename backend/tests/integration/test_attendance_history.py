"""Integração — attendance_history: híbrido LI+órfãos, ownership, conversa, stats."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.campaign import Campaign
from app.services.attendance_history import (
    assert_orphan_contact_access,
    fetch_conversation_messages,
    fetch_interaction_stats,
    get_attendance_conversation_by_contact,
    get_receptive_pool_owner_id,
    list_attendance_history,
)
from app.services.contact_normalization import canonical_contact_ids
from tests.integration.helpers import (
    OwnerContext,
    create_activation_records,
    create_interaction_record,
    create_lead_interaction,
    create_lead_on_base,
    create_owner_context,
    get_admin_user,
)

pytestmark = pytest.mark.integration

BASE_TIME = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
ORPHAN_CONTACT = "whatsapp:+5511999000001"


async def test_inbound_without_acionamento_appears_in_attendance(
    owner_ctx: OwnerContext, db_session
) -> None:
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="inbound-att", telefone="5511666555444"
    )
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=None,
        data_ultimo_contato=BASE_TIME,
    )
    await create_activation_records(db_session, owner_ctx, 1, base_time=BASE_TIME)

    items, total = await list_attendance_history(
        db_session, owner_ctx.user, skip=0, limit=50
    )

    assert total >= 2
    contacts = {item.contact_user_id for item in items}
    assert "5511666555444" in contacts or "+5511666555444" in contacts


async def test_hybrid_includes_orphan_for_receptive_owner(
    system_seeds, db_session
) -> None:
    admin = await get_admin_user(db_session)
    await create_interaction_record(
        db_session,
        user_id=ORPHAN_CONTACT,
        message="Contato desconhecido",
        response="Olá, como posso ajudar?",
    )

    items, total = await list_attendance_history(
        db_session, admin, skip=0, limit=50
    )

    assert total >= 1
    orphan_items = [i for i in items if i.lead_interaction_id is None]
    assert len(orphan_items) >= 1
    assert any(
        ORPHAN_CONTACT in canonical_contact_ids("whatsapp", i.contact_user_id)
        or i.contact_user_id in canonical_contact_ids("whatsapp", ORPHAN_CONTACT)
        for i in orphan_items
    )


async def test_orphan_not_visible_to_other_tenant(
    system_seeds, second_owner, db_session
) -> None:
    await create_interaction_record(
        db_session,
        user_id=ORPHAN_CONTACT,
        message="Privado",
        response="Resposta",
    )

    items, total = await list_attendance_history(
        db_session, second_owner, skip=0, limit=50
    )

    assert total == 0
    assert items == []


async def test_assert_orphan_contact_access_enforces_receptive_owner(
    system_seeds, db_session, second_owner
) -> None:
    admin = await get_admin_user(db_session)
    await create_interaction_record(
        db_session,
        user_id=ORPHAN_CONTACT,
        message="Thread órfã",
        response="Ok",
    )

    await assert_orphan_contact_access(
        db_session, admin, "whatsapp", ORPHAN_CONTACT
    )

    with pytest.raises(HTTPException) as exc:
        await assert_orphan_contact_access(
            db_session, second_owner, "whatsapp", ORPHAN_CONTACT
        )
    assert exc.value.status_code == 404


async def test_attendance_pagination_and_filters(
    owner_ctx: OwnerContext, db_session
) -> None:
    other_campaign = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="Att Filter Camp",
        status="active",
    )
    db_session.add(other_campaign)
    await db_session.flush()

    await create_activation_records(
        db_session, owner_ctx, 5, base_time=BASE_TIME, channel_type="whatsapp"
    )
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="att-tg", telefone="5511555444333"
    )
    lead.aux_values = {"telegram_id": "777888999"}
    await db_session.flush()
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=other_campaign.id,
        channel_type="telegram",
        status="convertido",
        data_acionamento=BASE_TIME,
        data_ultimo_contato=BASE_TIME,
    )

    page1, total = await list_attendance_history(
        db_session, owner_ctx.user, skip=0, limit=3
    )
    page2, _ = await list_attendance_history(
        db_session, owner_ctx.user, skip=3, limit=3
    )
    assert total == 6
    assert len(page1) == 3
    assert len(page2) == 3

    tg_items, tg_total = await list_attendance_history(
        db_session,
        owner_ctx.user,
        skip=0,
        limit=50,
        channel_type="telegram",
    )
    assert tg_total == 1
    assert tg_items[0].channel == "telegram"

    open_items, open_total = await list_attendance_history(
        db_session,
        owner_ctx.user,
        skip=0,
        limit=50,
        open_only=True,
    )
    assert open_total == 5
    assert all(item.status != "convertido" for item in open_items)


async def test_attendance_ownership_isolates_tenants(
    owner_ctx: OwnerContext, second_owner, db_session
) -> None:
    await create_activation_records(db_session, owner_ctx, 2, base_time=BASE_TIME)
    other_ctx = await create_owner_context(db_session, email_suffix="att-other")
    await create_activation_records(db_session, other_ctx, 3, base_time=BASE_TIME)

    _, owner_total = await list_attendance_history(
        db_session, owner_ctx.user, skip=0, limit=50
    )
    _, other_total = await list_attendance_history(
        db_session, other_ctx.user, skip=0, limit=50
    )
    _, second_total = await list_attendance_history(
        db_session, second_owner, skip=0, limit=50
    )

    assert owner_total == 2
    assert other_total == 3
    assert second_total == 0


async def test_conversation_messages_merge_whatsapp_variants(
    owner_ctx: OwnerContext, db_session
) -> None:
    phone = "5511444333222"
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="conv", telefone=phone
    )
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=BASE_TIME,
        data_ultimo_contato=BASE_TIME,
    )
    t0 = BASE_TIME
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{phone}",
        message="Oi",
        response="Olá!",
        created_at=t0,
    )
    await create_interaction_record(
        db_session,
        user_id=f"+{phone}",
        message="Tudo bem?",
        response="Sim!",
        created_at=t0.replace(hour=t0.hour + 1),
    )

    messages = await fetch_conversation_messages(
        db_session, "whatsapp", phone
    )

    assert len(messages) == 4
    assert messages[0].role == "user"
    assert messages[0].content == "Oi"
    assert messages[2].role == "user"
    assert messages[2].content == "Tudo bem?"


async def test_build_conversation_response_for_orphan(
    system_seeds, db_session
) -> None:
    admin = await get_admin_user(db_session)
    await create_interaction_record(
        db_session,
        user_id=ORPHAN_CONTACT,
        message="Pergunta órfã",
        response="Resposta órfã",
    )

    response = await get_attendance_conversation_by_contact(
        db_session, admin, "whatsapp", ORPHAN_CONTACT
    )

    assert response.lead_interaction_id is None
    assert len(response.messages) == 2
    assert response.messages[0].content == "Pergunta órfã"
    assert response.messages[1].content == "Resposta órfã"


async def test_fetch_interaction_stats_aggregates_known_messages(
    db_session,
) -> None:
    contact = "5511333222111"
    t0 = BASE_TIME
    await create_interaction_record(
        db_session,
        user_id=contact,
        message="A",
        response="B",
        created_at=t0,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{contact}",
        message="C",
        response="D",
        created_at=t0.replace(hour=t0.hour + 2),
    )

    variants = canonical_contact_ids("whatsapp", contact)
    stats = await fetch_interaction_stats(db_session, variants)

    assert stats.message_count == 2
    assert stats.first_at is not None
    assert stats.last_at is not None
    assert stats.last_preview is not None
    assert "D" in (stats.last_preview or "")


async def test_telegram_chat_id_not_misclassified_as_whatsapp_orphan(
    owner_ctx: OwnerContext, db_session
) -> None:
    """Numeric telegram_id must not appear as whatsapp orphan when LI exists."""
    chat_id = "5043259127"
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="tg-att", telefone="5511999000111"
    )
    lead.aux_values = {"telegram_id": chat_id}
    await db_session.flush()
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="telegram",
        status="em_andamento",
        data_acionamento=BASE_TIME,
        data_ultimo_contato=BASE_TIME,
    )
    await create_interaction_record(
        db_session,
        user_id=chat_id,
        message="Oi telegram",
        response="Olá!",
        created_at=BASE_TIME,
    )

    items, total = await list_attendance_history(
        db_session, owner_ctx.user, skip=0, limit=50
    )

    tg_items = [
        i
        for i in items
        if i.contact_user_id == chat_id or chat_id in (i.contact_user_id or "")
    ]
    assert len(tg_items) == 1
    assert tg_items[0].channel == "telegram"
    assert tg_items[0].lead_interaction_id is not None
    assert tg_items[0].status == "em_andamento"


async def test_receptive_pool_owner_is_seed_admin(system_seeds, db_session) -> None:
    admin = await get_admin_user(db_session)
    pool_owner = await get_receptive_pool_owner_id(db_session)

    assert pool_owner == admin.id
