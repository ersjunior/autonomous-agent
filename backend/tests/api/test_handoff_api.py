"""Camada 3 — handoff API: active, assume, finalize, reactivate (Redis + DB + tenant)."""

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


def _handoff_owner_id(owner_ctx: OwnerContext) -> str:
    """Regra: lead com base+campanha → campaign.user_id."""
    return str(owner_ctx.campaign.user_id)


def _enter_human_for_owner(owner_ctx: OwnerContext, *, channel: str = "whatsapp") -> str:
    """Estado de modo humano com owner_user_id do tenant."""
    contact = owner_ctx.lead.telefone_1
    enter_human_mode(
        channel,
        contact,
        intent="escalate",
        owner_user_id=_handoff_owner_id(owner_ctx),
    )
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
    contact = _enter_human_for_owner(owner_ctx)
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
    contact = _enter_human_for_owner(owner_ctx)
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
    contact = _enter_human_for_owner(owner_ctx)
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
    contact = _enter_human_for_owner(owner_ctx)
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
    contact = _enter_human_for_owner(owner_ctx)
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
    contact = _enter_human_for_owner(owner_ctx)
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


# --- Isolamento de tenant ---


async def test_handoff_active_filters_by_tenant_owner_sees_only_own(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
) -> None:
    owner_contact = _enter_human_for_owner(owner_ctx)
    other_ctx = await create_owner_context(db_session, email_suffix="ho-other")
    other_contact = other_ctx.lead.telefone_1
    enter_human_mode(
        "telegram",
        other_contact,
        intent="escalate",
        owner_user_id=str(other_ctx.campaign.user_id),
    )

    response = await auth_client.get(f"{HANDOFF}/active")
    assert response.status_code == 200
    ids = {(r["channel"], r["user_id"]) for r in response.json()}
    assert ids == {("whatsapp", owner_contact)}


async def test_handoff_active_second_owner_sees_only_own(
    test_app,
    client,
    owner_ctx,
    db_session,
    clean_redis,
) -> None:
    _enter_human_for_owner(owner_ctx)
    other_ctx = await create_owner_context(db_session, email_suffix="ho-other2")
    other_contact = other_ctx.lead.telefone_1
    enter_human_mode(
        "telegram",
        other_contact,
        intent="escalate",
        owner_user_id=str(other_ctx.campaign.user_id),
    )

    from app.core.security import get_current_user

    async def override_get_current_user():
        return other_ctx.user

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        response = await client.get(f"{HANDOFF}/active")
    finally:
        test_app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    ids = {(r["channel"], r["user_id"]) for r in response.json()}
    assert ids == {("telegram", other_contact)}


async def test_handoff_assume_foreign_owner_returns_404(
    other_auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = _enter_human_for_owner(owner_ctx)
    response = await other_auth_client.post(
        f"{HANDOFF}/assume",
        json=_handoff_payload("whatsapp", contact),
    )
    assert response.status_code == 404
    assert not is_assumed("whatsapp", contact)


async def test_handoff_finalize_foreign_owner_returns_404(
    other_auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = _enter_human_for_owner(owner_ctx)
    response = await other_auth_client.post(
        f"{HANDOFF}/finalize",
        json={
            "channel": "whatsapp",
            "user_id": contact,
            "tabulacao_codigo": "NEG:SUCESSO",
        },
    )
    assert response.status_code == 404
    assert is_in_human_mode("whatsapp", contact)


async def test_handoff_reactivate_foreign_owner_returns_404(
    other_auth_client,
    owner_ctx,
    clean_redis,
) -> None:
    contact = _enter_human_for_owner(owner_ctx)
    response = await other_auth_client.post(
        f"{HANDOFF}/reactivate",
        json=_handoff_payload("whatsapp", contact),
    )
    assert response.status_code == 404
    assert is_in_human_mode("whatsapp", contact)
