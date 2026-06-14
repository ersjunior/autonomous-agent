"""Camada 3 — handoff API: active, assume, finalize, reactivate (Redis + DB)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.lead_interaction import LeadInteraction
from app.services.human_handoff import (
    enter_human_mode,
    is_assumed,
    is_in_human_mode,
)
from tests.integration.helpers import (
    OwnerContext,
    create_owner_context,
    tabulacao_codigo_for,
)

pytestmark = pytest.mark.api

HANDOFF = "/api/v1/handoff"


def _handoff_payload(channel: str, user_id: str) -> dict:
    return {"channel": channel, "user_id": user_id}


async def _enter_human_for_lead(owner_ctx: OwnerContext, *, channel: str = "whatsapp") -> str:
    """Estado de modo humano via serviço real (não Redis cru)."""
    contact = owner_ctx.lead.telefone_1
    enter_human_mode(channel, contact, intent="escalate")
    return contact


# --- GET /active ---


async def test_handoff_active_empty_returns_200(
    auth_client,
    clean_redis,
) -> None:
    response = await auth_client.get(f"{HANDOFF}/active")
    assert response.status_code == 200
    assert response.json() == []


async def test_handoff_active_lists_human_mode_contact(
    auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = await _enter_human_for_lead(owner_ctx)
    response = await auth_client.get(f"{HANDOFF}/active")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["channel"] == "whatsapp"
    assert body[0]["user_id"] == contact
    assert body[0]["is_assumed"] is False


# --- POST /assume ---


async def test_handoff_assume_returns_200(
    auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = await _enter_human_for_lead(owner_ctx)
    response = await auth_client.post(
        f"{HANDOFF}/assume",
        json=_handoff_payload("whatsapp", contact),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "Atendimento assumido"
    assert is_assumed("whatsapp", contact)


async def test_handoff_assume_without_human_mode_returns_404(
    auth_client,
    clean_redis,
) -> None:
    response = await auth_client.post(
        f"{HANDOFF}/assume",
        json=_handoff_payload("whatsapp", "5511999999999"),
    )
    assert response.status_code == 404
    assert "modo humano" in response.json()["detail"].lower()


# --- POST /finalize ---


async def test_handoff_finalize_returns_200_persists_and_clears_redis(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_capacity_release,
) -> None:
    contact = await _enter_human_for_lead(owner_ctx)
    response = await auth_client.post(
        f"{HANDOFF}/finalize",
        json={
            "channel": "whatsapp",
            "user_id": contact,
            "tabulacao_codigo": "NEG:SUCESSO",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "Handoff finalizado"
    assert not is_in_human_mode("whatsapp", contact)

    result = await db_session.execute(
        select(LeadInteraction).where(
            LeadInteraction.lead_id == owner_ctx.lead.id,
            LeadInteraction.campaign_id == owner_ctx.campaign.id,
            LeadInteraction.channel_type == "whatsapp",
        )
    )
    li = result.scalar_one()
    assert li.status == "convertido"
    assert li.tabulacao_origem == "HANDOFF_FINALIZE"
    assert await tabulacao_codigo_for(db_session, li) == "NEG:SUCESSO"


async def test_handoff_finalize_invalid_tabulacao_returns_400(
    auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = await _enter_human_for_lead(owner_ctx)
    response = await auth_client.post(
        f"{HANDOFF}/finalize",
        json={
            "channel": "whatsapp",
            "user_id": contact,
            "tabulacao_codigo": "NEG:INEXISTENTE",
        },
    )
    assert response.status_code == 400
    assert "Tabulação inválida" in response.json()["detail"]
    assert is_in_human_mode("whatsapp", contact)


async def test_handoff_finalize_without_human_mode_returns_404(
    auth_client,
    clean_redis,
) -> None:
    response = await auth_client.post(
        f"{HANDOFF}/finalize",
        json={
            "channel": "whatsapp",
            "user_id": "5511888777666",
            "tabulacao_codigo": "NEG:SUCESSO",
        },
    )
    assert response.status_code == 404


async def test_handoff_finalize_invalid_payload_returns_422(
    auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = await _enter_human_for_lead(owner_ctx)
    response = await auth_client.post(
        f"{HANDOFF}/finalize",
        json={"channel": "whatsapp", "user_id": contact},
    )
    assert response.status_code == 422


# --- POST /reactivate ---


async def test_handoff_reactivate_returns_200_clears_redis(
    auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = await _enter_human_for_lead(owner_ctx)
    response = await auth_client.post(
        f"{HANDOFF}/reactivate",
        json=_handoff_payload("whatsapp", contact),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reactivated"] is True
    assert not is_in_human_mode("whatsapp", contact)


async def test_handoff_reactivate_not_in_human_mode_returns_false(
    auth_client,
    clean_redis,
) -> None:
    response = await auth_client.post(
        f"{HANDOFF}/reactivate",
        json=_handoff_payload("whatsapp", "5511777666555"),
    )
    assert response.status_code == 200
    assert response.json()["reactivated"] is False


# --- Escopo / ownership ---


async def test_handoff_active_no_tenant_filter_owner_sees_all(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
) -> None:
    """
    Divergência documentada: /handoff/active não filtra por dono do lead —
    qualquer usuário autenticado vê todas as chaves human_mode:* no Redis.
    """
    owner_contact = await _enter_human_for_lead(owner_ctx)
    other_ctx = await create_owner_context(db_session, email_suffix="ho-other")
    other_contact = other_ctx.lead.telefone_1
    enter_human_mode("telegram", other_contact, intent="escalate")

    response = await auth_client.get(f"{HANDOFF}/active")
    assert response.status_code == 200
    ids = {(r["channel"], r["user_id"]) for r in response.json()}
    assert ("whatsapp", owner_contact) in ids
    assert ("telegram", other_contact) in ids
    assert len(ids) == 2


async def test_handoff_active_no_tenant_filter_other_user_same_list(
    other_auth_client,
    owner_ctx,
    db_session,
    clean_redis,
) -> None:
    owner_contact = await _enter_human_for_lead(owner_ctx)
    other_ctx = await create_owner_context(db_session, email_suffix="ho-other2")
    other_contact = other_ctx.lead.telefone_1
    enter_human_mode("telegram", other_contact, intent="escalate")

    response = await other_auth_client.get(f"{HANDOFF}/active")
    assert response.status_code == 200
    ids = {(r["channel"], r["user_id"]) for r in response.json()}
    assert ("whatsapp", owner_contact) in ids
    assert ("telegram", other_contact) in ids


async def test_handoff_assume_any_authenticated_user_can_act(
    other_auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    """Assume não valida ownership — basta existir modo humano no Redis."""
    contact = await _enter_human_for_lead(owner_ctx)
    response = await other_auth_client.post(
        f"{HANDOFF}/assume",
        json=_handoff_payload("whatsapp", contact),
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert is_assumed("whatsapp", contact)
