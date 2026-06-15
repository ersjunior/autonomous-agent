"""Camada 3 — monitoring API: attendance-history, messages, contact-messages."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
from tests.integration.helpers import (
    OwnerContext,
    create_activation_records,
    create_interaction_record,
    create_lead_interaction,
    create_lead_on_base,
    create_owner_context,
    get_admin_user,
)

pytestmark = pytest.mark.api

MONITORING = "/api/v1/monitoring"
BASE_TIME = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
ORPHAN_CONTACT = "whatsapp:+5511999000001"


@pytest_asyncio.fixture
async def admin_auth_client(test_app, client: AsyncClient, system_seeds, db_session) -> AsyncGenerator[AsyncClient, None]:
    """Cliente autenticado como admin (dono do pool receptivo / órfãos)."""
    from app.core.security import get_current_user

    admin = await get_admin_user(db_session)

    async def override_get_current_user():
        return admin

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    yield client
    test_app.dependency_overrides.pop(get_current_user, None)


async def _seed_li_with_thread(
    db_session,
    owner_ctx: OwnerContext,
    *,
    suffix: str = "thread",
    phone: str = "5511444333222",
) -> uuid.UUID:
    """LI + interactions para thread de mensagens."""
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix=suffix, telefone=phone
    )
    li = await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=BASE_TIME,
        data_ultimo_contato=BASE_TIME,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{phone}",
        message="Oi",
        response="Olá!",
        created_at=BASE_TIME,
    )
    await create_interaction_record(
        db_session,
        user_id=f"+{phone}",
        message="Tudo bem?",
        response="Sim!",
        created_at=BASE_TIME.replace(hour=BASE_TIME.hour + 1),
    )
    return li.id


# --- attendance-history ---


async def test_attendance_history_requires_auth(client) -> None:
    response = await client.get(f"{MONITORING}/attendance-history")
    assert response.status_code == 401


async def test_attendance_history_returns_200_paginated(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 5, base_time=BASE_TIME)
    response = await auth_client.get(f"{MONITORING}/attendance-history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert body["skip"] == 0
    assert body["limit"] == 50


async def test_attendance_history_filter_by_campaign(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)
    response = await auth_client.get(
        f"{MONITORING}/attendance-history",
        params={"campaign_id": str(owner_ctx.campaign.id)},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3


async def test_attendance_history_filter_by_channel(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, channel_type="whatsapp"
    )
    for i in range(3):
        lead = await create_lead_on_base(
            db_session, owner_ctx, suffix=f"tg-{i}", telefone=f"5511999887{i:03d}"
        )
        lead.aux_values = {"telegram_id": f"777888{i:03d}"}
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

    response = await auth_client.get(
        f"{MONITORING}/attendance-history",
        params={"channel_type": "telegram"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert all(item["channel"] == "telegram" for item in body["items"])


async def test_attendance_history_filter_by_status(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, status="convertido"
    )
    await create_activation_records(
        db_session, owner_ctx, 3, base_time=BASE_TIME, status="em_andamento"
    )
    response = await auth_client.get(
        f"{MONITORING}/attendance-history",
        params={"status": "convertido"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_attendance_history_open_only_excludes_terminal(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, status="convertido"
    )
    await create_activation_records(
        db_session, owner_ctx, 4, base_time=BASE_TIME, status="em_andamento"
    )
    response = await auth_client.get(
        f"{MONITORING}/attendance-history",
        params={"open_only": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert all(item["status"] != "convertido" for item in body["items"])


async def test_attendance_history_invalid_skip_returns_400(auth_client) -> None:
    response = await auth_client.get(
        f"{MONITORING}/attendance-history",
        params={"skip": -1},
    )
    assert response.status_code == 400


async def test_attendance_history_invalid_limit_returns_400(auth_client) -> None:
    for bad_limit in (0, 201):
        response = await auth_client.get(
            f"{MONITORING}/attendance-history",
            params={"limit": bad_limit},
        )
        assert response.status_code == 400


async def test_attendance_history_owner_sees_own_records(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)
    other_ctx = await create_owner_context(db_session, email_suffix="mon-other")
    await create_activation_records(db_session, other_ctx, 2, base_time=BASE_TIME)

    response = await auth_client.get(f"{MONITORING}/attendance-history")
    assert response.status_code == 200
    assert response.json()["total"] == 3


async def test_attendance_history_second_owner_sees_empty(
    other_auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)

    response = await other_auth_client.get(f"{MONITORING}/attendance-history")
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_attendance_history_owner_sees_system_campaign_li(
    auth_client,
    owner_ctx,
    system_seeds,
    db_session,
) -> None:
    """Campanhas is_system entram via campaign_visibility_filter."""
    admin = await get_admin_user(db_session)
    system_agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Receptivo",
                Agent.mode == AgentMode.RECEPTIVE,
            )
        )
    ).scalar_one()
    system_campaign = Campaign(
        user_id=admin.id,
        agent_id=system_agent.id,
        name="Campanha System Att",
        status="active",
        is_system=True,
    )
    db_session.add(system_campaign)
    await db_session.flush()

    system_base = LeadBase(
        campaign_id=system_campaign.id,
        data_recebimento=date.today(),
        source=LeadBaseSource.MANUAL,
    )
    db_session.add(system_base)
    await db_session.flush()

    lead = Lead(
        user_id=owner_ctx.user.id,
        lead_base_id=system_base.id,
        id_cliente="CLI-SYS-ATT",
        nome_cliente="Lead System Att",
        telefone_1="5511888777666",
    )
    db_session.add(lead)
    await db_session.flush()
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=system_campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=BASE_TIME,
        data_ultimo_contato=BASE_TIME,
    )

    response = await auth_client.get(f"{MONITORING}/attendance-history")
    assert response.status_code == 200
    campaign_ids = {item["campaign_id"] for item in response.json()["items"]}
    assert str(system_campaign.id) in campaign_ids


# --- attendance/{li_id}/messages ---


async def test_attendance_messages_by_li_returns_200_thread(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    li_id = await _seed_li_with_thread(db_session, owner_ctx)
    response = await auth_client.get(f"{MONITORING}/attendance/{li_id}/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["lead_interaction_id"] == str(li_id)
    assert len(body["messages"]) == 4
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Oi"
    assert body["messages"][1]["role"] == "assistant"
    assert body["messages"][1]["content"] == "Olá!"


async def test_attendance_messages_foreign_li_returns_404(
    auth_client,
    db_session,
) -> None:
    other_ctx = await create_owner_context(db_session, email_suffix="msg-foreign")
    li_id = await _seed_li_with_thread(db_session, other_ctx, suffix="foreign")
    response = await auth_client.get(f"{MONITORING}/attendance/{li_id}/messages")
    assert response.status_code == 404


# --- contact-messages (órfãos) ---


async def test_contact_messages_orphan_returns_200_for_receptive_owner(
    admin_auth_client,
    system_seeds,
    db_session,
) -> None:
    await create_interaction_record(
        db_session,
        user_id=ORPHAN_CONTACT,
        message="Pergunta órfã",
        response="Resposta órfã",
    )
    response = await admin_auth_client.get(
        f"{MONITORING}/contact-messages",
        params={"channel": "whatsapp", "contact_user_id": ORPHAN_CONTACT},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lead_interaction_id"] is None
    assert len(body["messages"]) == 2
    assert body["messages"][0]["content"] == "Pergunta órfã"


async def test_contact_messages_orphan_other_tenant_returns_404(
    other_auth_client,
    system_seeds,
    db_session,
) -> None:
    await create_interaction_record(
        db_session,
        user_id=ORPHAN_CONTACT,
        message="Privado",
        response="Resposta",
    )
    response = await other_auth_client.get(
        f"{MONITORING}/contact-messages",
        params={"channel": "whatsapp", "contact_user_id": ORPHAN_CONTACT},
    )
    assert response.status_code == 404


async def test_contact_messages_missing_query_params_returns_422(
    auth_client,
) -> None:
    response = await auth_client.get(f"{MONITORING}/contact-messages")
    assert response.status_code == 422


# --- active-conversations ---


def _recent_time(minutes_ago: int = 2) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


async def test_active_conversations_requires_auth(client) -> None:
    response = await client.get(f"{MONITORING}/active-conversations")
    assert response.status_code == 401


async def test_active_conversations_returns_recent_with_agent(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    recent = _recent_time(2)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="active-now", telefone="5511333444555"
    )
    li = await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=recent,
        data_ultimo_contato=recent,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{lead.telefone_1}",
        message="Oi agora",
        response="Olá!",
        created_at=recent,
    )

    response = await auth_client.get(f"{MONITORING}/active-conversations")
    assert response.status_code == 200
    body = response.json()
    assert body["window_minutes"] == 10
    assert body["total"] >= 1
    match = next(
        (item for item in body["items"] if item["lead_interaction_id"] == str(li.id)),
        None,
    )
    assert match is not None
    assert match["agent_id"] == str(owner_ctx.agent.id)
    assert match["agent_name"] == owner_ctx.agent.name
    assert match["lead_nome"] == lead.nome_cliente
    assert match["channel"] == "whatsapp"
    assert match["status"] == "em_andamento"
    assert match["last_message_preview"] is not None
    assert match["message_count"] >= 1
    assert match["last_activity_at"] is not None


async def test_active_conversations_excludes_old_outside_window(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    old = _recent_time(30)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="active-old", telefone="5511222333444"
    )
    li = await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=old,
        data_ultimo_contato=old,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{lead.telefone_1}",
        message="Antiga",
        response="Resposta",
        created_at=old,
    )

    response = await auth_client.get(
        f"{MONITORING}/active-conversations",
        params={"window_minutes": 10},
    )
    assert response.status_code == 200
    ids = {item["lead_interaction_id"] for item in response.json()["items"]}
    assert str(li.id) not in ids


async def test_active_conversations_excludes_terminal_status(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    recent = _recent_time(1)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="active-terminal", telefone="5511111222333"
    )
    li = await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="convertido",
        data_acionamento=recent,
        data_ultimo_contato=recent,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{lead.telefone_1}",
        message="Fechou",
        response="Obrigado",
        created_at=recent,
    )

    response = await auth_client.get(f"{MONITORING}/active-conversations")
    assert response.status_code == 200
    ids = {item["lead_interaction_id"] for item in response.json()["items"]}
    assert str(li.id) not in ids


async def test_active_conversations_owner_sees_own_records_only(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    recent = _recent_time(1)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="active-owner", telefone="5511000111222"
    )
    await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=recent,
        data_ultimo_contato=recent,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{lead.telefone_1}",
        message="Minha",
        response="Sua",
        created_at=recent,
    )

    other_ctx = await create_owner_context(db_session, email_suffix="active-other")
    other_lead = await create_lead_on_base(
        db_session, other_ctx, suffix="other-active", telefone="5511000333444"
    )
    await create_lead_interaction(
        db_session,
        lead_id=other_lead.id,
        campaign_id=other_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=recent,
        data_ultimo_contato=recent,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{other_lead.telefone_1}",
        message="Outro",
        response="Tenant",
        created_at=recent,
    )

    response = await auth_client.get(f"{MONITORING}/active-conversations")
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_active_conversations_all_period_includes_old_non_terminal(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    old = _recent_time(30)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="active-all-period", telefone="5511888777666"
    )
    li = await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=old,
        data_ultimo_contato=old,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{lead.telefone_1}",
        message="Antiga mas aberta",
        response="Resposta",
        created_at=old,
    )

    response = await auth_client.get(
        f"{MONITORING}/active-conversations",
        params={"window_minutes": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window_minutes"] == 0
    ids = {item["lead_interaction_id"] for item in body["items"]}
    assert str(li.id) in ids


async def test_active_conversations_large_window_includes_old(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    old = _recent_time(30)
    lead = await create_lead_on_base(
        db_session, owner_ctx, suffix="active-day", telefone="5511777666555"
    )
    li = await create_lead_interaction(
        db_session,
        lead_id=lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=old,
        data_ultimo_contato=old,
    )
    await create_interaction_record(
        db_session,
        user_id=f"whatsapp:+{lead.telefone_1}",
        message="Dentro do dia",
        response="Ok",
        created_at=old,
    )

    response = await auth_client.get(
        f"{MONITORING}/active-conversations",
        params={"window_minutes": 1440},
    )
    assert response.status_code == 200
    ids = {item["lead_interaction_id"] for item in response.json()["items"]}
    assert str(li.id) in ids


async def test_active_conversations_invalid_window_returns_422(auth_client) -> None:
    response = await auth_client.get(
        f"{MONITORING}/active-conversations",
        params={"window_minutes": 600000},
    )
    assert response.status_code == 422
