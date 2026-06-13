"""Integração — upsert_lead_interaction, find_lead_by_channel_user, terminal → Redis release."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.lead_interaction import LeadInteraction
from tests.integration.helpers import OwnerContext, tabulacao_codigo_for
from worker.tasks.lead_tracking import (
    find_lead_by_channel_user,
    track_inbound_lead_interaction,
    upsert_lead_interaction,
)

pytestmark = pytest.mark.integration


async def _count_li_for_triplet(
    session,
    lead_id: uuid.UUID,
    campaign_id: uuid.UUID,
    channel_type: str,
) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(LeadInteraction)
        .where(
            LeadInteraction.lead_id == lead_id,
            LeadInteraction.campaign_id == campaign_id,
            LeadInteraction.channel_type == channel_type.lower(),
        )
    )


# --- 1. CREATE / UPDATE (unicidade da tripla) ---


async def test_upsert_creates_new_lead_interaction(owner_ctx: OwnerContext, db_session) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="pendente",
    )

    assert record.id is not None
    assert record.status == "pendente"
    assert record.tentativas == 0
    assert record.data_acionamento is None
    assert record.data_ultimo_contato is None
    assert record.data_ultima_tentativa is None
    assert await _count_li_for_triplet(
        db_session, owner_ctx.lead.id, owner_ctx.campaign.id, "whatsapp"
    ) == 1


async def test_upsert_updates_same_triplet_not_duplicate(
    owner_ctx: OwnerContext, db_session
) -> None:
    first = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="acionado",
        devolutiva="primeira",
    )
    second = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="em_andamento",
        devolutiva="atualizada",
    )

    assert second.id == first.id
    assert second.status == "em_andamento"
    assert second.devolutiva == "atualizada"
    assert await _count_li_for_triplet(
        db_session, owner_ctx.lead.id, owner_ctx.campaign.id, "whatsapp"
    ) == 1


# --- 2. Timestamps ---


async def test_touch_inbound_updates_data_ultimo_contato(
    owner_ctx: OwnerContext, db_session
) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        touch_inbound=True,
    )

    assert record.data_ultimo_contato is not None
    assert record.data_ultima_tentativa is None


async def test_outbound_attempt_updates_tentativas_and_data_ultima_tentativa(
    owner_ctx: OwnerContext, db_session
) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        set_acionamento=True,
        record_outbound_attempt=True,
    )

    assert record.data_acionamento is not None
    assert record.tentativas == 1
    assert record.data_ultima_tentativa is not None

    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        record_outbound_attempt=True,
    )

    assert record.tentativas == 2


async def test_set_acionamento_only_on_first_outbound(
    owner_ctx: OwnerContext, db_session
) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        set_acionamento=True,
    )
    first_acionamento = record.data_acionamento

    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        set_acionamento=True,
    )

    assert record.data_acionamento == first_acionamento


# --- 3. find_lead_by_channel_user ---


async def test_find_lead_by_phone_whatsapp(owner_ctx: OwnerContext, db_session) -> None:
    found = await find_lead_by_channel_user(
        db_session, "whatsapp", "+55 (11) 99988-7766"
    )

    assert found is not None
    assert found.id == owner_ctx.lead.id


async def test_find_lead_by_phone_voice(owner_ctx: OwnerContext, db_session) -> None:
    found = await find_lead_by_channel_user(db_session, "voice", "5511999887766")

    assert found is not None
    assert found.id == owner_ctx.lead.id


async def test_find_lead_by_telegram_jsonb(owner_ctx: OwnerContext, db_session) -> None:
    telegram_id = "987654321"
    owner_ctx.lead.aux_values = {"telegram_id": telegram_id}
    await db_session.flush()

    found = await find_lead_by_channel_user(db_session, "telegram", telegram_id)

    assert found is not None
    assert found.id == owner_ctx.lead.id


async def test_find_lead_returns_none_for_unknown_contact(
    owner_ctx: OwnerContext, db_session
) -> None:
    assert await find_lead_by_channel_user(db_session, "whatsapp", "5599999999999") is None
    assert await find_lead_by_channel_user(db_session, "telegram", "000000000") is None


# --- 4. Terminal → release Redis (mock) ---


async def test_terminal_transition_triggers_capacity_release(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="em_andamento",
    )

    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="convertido",
    )

    assert record.status == "convertido"
    lead_id = str(owner_ctx.lead.id)
    assert mock_capacity_release["slot_calls"] == [(lead_id, "whatsapp")]
    assert mock_capacity_release["outbound_calls"] == [(lead_id, "whatsapp")]
    assert mock_capacity_release["receptive_calls"] == [(lead_id, "whatsapp")]


async def test_non_terminal_transition_does_not_release_capacity(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="em_andamento",
    )

    assert mock_capacity_release["slot_calls"] == []
    assert mock_capacity_release["outbound_calls"] == []
    assert mock_capacity_release["receptive_calls"] == []


async def test_already_terminal_does_not_release_again(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="convertido",
    )
    assert len(mock_capacity_release["slot_calls"]) == 1

    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="convertido",
    )
    assert len(mock_capacity_release["slot_calls"]) == 1


async def test_voice_terminal_skips_receptive_release(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "voice",
        status="recusou",
    )

    lead_id = str(owner_ctx.lead.id)
    assert mock_capacity_release["slot_calls"] == [(lead_id, "voice")]
    assert mock_capacity_release["outbound_calls"] == [(lead_id, "voice")]
    assert mock_capacity_release["receptive_calls"] == []


# --- 5. track_inbound_lead_interaction ---


async def test_track_inbound_creates_and_updates_li(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    phone = owner_ctx.lead.telefone_1 or "5511999887766"

    created = await track_inbound_lead_interaction(
        db_session,
        "whatsapp",
        phone,
        "Olá, tenho uma dúvida",
        "question",
    )

    assert created is not None
    assert created.status == "em_andamento"
    assert created.devolutiva == "Olá, tenho uma dúvida"
    assert created.data_ultimo_contato is not None
    assert created.tabulacao_id is None
    first_id = created.id

    updated = await track_inbound_lead_interaction(
        db_session,
        "whatsapp",
        phone,
        "Ainda aguardo resposta",
        "question",
    )

    assert updated is not None
    assert updated.id == first_id
    assert updated.devolutiva == "Ainda aguardo resposta"
    assert await _count_li_for_triplet(
        db_session, owner_ctx.lead.id, owner_ctx.campaign.id, "whatsapp"
    ) == 1


async def test_track_inbound_purchase_applies_tabulation(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    phone = owner_ctx.lead.telefone_1 or "5511999887766"

    record = await track_inbound_lead_interaction(
        db_session,
        "whatsapp",
        phone,
        "Quero fechar a compra",
        "purchase",
    )

    assert record is not None
    assert record.status == "convertido"
    assert await tabulacao_codigo_for(db_session, record) == "NEG:VENDA"
    assert record.tabulacao_origem == "INTENT"
    assert len(mock_capacity_release["outbound_calls"]) == 1


async def test_track_inbound_escalated_applies_neg_escalado(
    owner_ctx: OwnerContext, db_session, mock_capacity_release
) -> None:
    phone = owner_ctx.lead.telefone_1 or "5511999887766"

    record = await track_inbound_lead_interaction(
        db_session,
        "whatsapp",
        phone,
        "Preciso falar com um humano",
        "question",
        escalated=True,
    )

    assert record is not None
    assert await tabulacao_codigo_for(db_session, record) == "NEG:ESCALADO"
    assert record.tabulacao_origem == "ESCALATION"


async def test_track_inbound_returns_none_for_unknown_contact(db_session) -> None:
    result = await track_inbound_lead_interaction(
        db_session,
        "whatsapp",
        "5599888776655",
        "Mensagem",
        "question",
    )
    assert result is None
