"""Camada 3 — CRUD + ownership de /leads via API."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.authorization import IMPORT_LEAD_DELETE_DETAIL, IMPORT_LEAD_EDIT_DETAIL
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
from tests.api.ownership_helpers import foreign_lead_id, foreign_owner_context

pytestmark = pytest.mark.api

BASE = "/api/v1/leads/"


def _lead_payload(lead_base_id: str, *, suffix: str | None = None) -> dict:
    tag = suffix or uuid.uuid4().hex[:8]
    return {
        "lead_base_id": lead_base_id,
        "id_cliente": f"CLI-{tag}",
        "nome_cliente": f"Lead {tag}",
        "telefone_1": "5511999887766",
    }


async def test_leads_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_leads_list_includes_owner_excludes_foreign(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    foreign_id = str(await foreign_lead_id(db_session))

    response = await auth_client.get(BASE)
    assert response.status_code == 200

    ids = {item["id"] for item in response.json()}
    assert str(owner_ctx.lead.id) in ids
    assert foreign_id not in ids


async def test_leads_create_returns_201_and_persists(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    payload = _lead_payload(str(owner_ctx.lead_base.id))
    response = await auth_client.post(BASE, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["nome_cliente"] == payload["nome_cliente"]
    assert body["lead_base_id"] == str(owner_ctx.lead_base.id)
    assert body["is_system"] is False

    persisted = await db_session.get(Lead, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.user_id == owner_ctx.user.id


async def test_leads_create_foreign_lead_base_returns_404(
    auth_client,
    db_session,
) -> None:
    other_ctx = await foreign_owner_context(db_session, suffix="lead-base-404")
    response = await auth_client.post(
        BASE,
        json=_lead_payload(str(other_ctx.lead_base.id)),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Lead base not found"


async def test_leads_create_import_base_returns_400(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    imported_base = LeadBase(
        campaign_id=owner_ctx.campaign.id,
        data_recebimento=date.today(),
        source=LeadBaseSource.IMPORT,
    )
    db_session.add(imported_base)
    await db_session.flush()

    response = await auth_client.post(
        BASE,
        json=_lead_payload(str(imported_base.id)),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot add leads individually to an imported base"


@pytest.mark.parametrize(
    "payload",
    [
        {"lead_base_id": str(uuid.uuid4()), "telefone_1": "5511999999999"},
        {"nome_cliente": "Sem base"},
    ],
)
async def test_leads_create_invalid_payload_returns_422(
    auth_client,
    payload: dict,
) -> None:
    response = await auth_client.post(BASE, json=payload)
    assert response.status_code == 422


async def test_leads_get_own_returns_200(auth_client, owner_ctx) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.lead.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(owner_ctx.lead.id)


async def test_leads_get_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_lead_id(db_session))
    response = await auth_client.get(f"{BASE}{foreign_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Lead not found"


async def test_leads_get_missing_returns_404(auth_client) -> None:
    response = await auth_client.get(f"{BASE}{uuid.uuid4()}")
    assert response.status_code == 404


async def test_leads_update_own_returns_200(auth_client, owner_ctx) -> None:
    response = await auth_client.put(
        f"{BASE}{owner_ctx.lead.id}",
        json={"nome_cliente": "Lead Atualizado"},
    )
    assert response.status_code == 200
    assert response.json()["nome_cliente"] == "Lead Atualizado"


async def test_leads_update_import_lead_returns_403(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    imported_base = LeadBase(
        campaign_id=owner_ctx.campaign.id,
        data_recebimento=date.today(),
        source=LeadBaseSource.IMPORT,
    )
    db_session.add(imported_base)
    await db_session.flush()

    imported_lead = Lead(
        user_id=owner_ctx.user.id,
        lead_base_id=imported_base.id,
        id_cliente="IMP-API",
        nome_cliente="Lead Importado",
    )
    db_session.add(imported_lead)
    await db_session.flush()

    response = await auth_client.put(
        f"{BASE}{imported_lead.id}",
        json={"nome_cliente": "Tentativa"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == IMPORT_LEAD_EDIT_DETAIL


async def test_leads_update_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_lead_id(db_session))
    response = await auth_client.put(
        f"{BASE}{foreign_id}",
        json={"nome_cliente": "Não deve alterar"},
    )
    assert response.status_code == 404


async def test_leads_delete_own_returns_204(auth_client, owner_ctx, db_session) -> None:
    create = await auth_client.post(
        BASE,
        json=_lead_payload(str(owner_ctx.lead_base.id)),
    )
    lead_id = create.json()["id"]

    response = await auth_client.delete(f"{BASE}{lead_id}")
    assert response.status_code == 204
    assert await db_session.get(Lead, uuid.UUID(lead_id)) is None


async def test_leads_delete_import_lead_returns_403(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    imported_base = LeadBase(
        campaign_id=owner_ctx.campaign.id,
        data_recebimento=date.today(),
        source=LeadBaseSource.IMPORT,
    )
    db_session.add(imported_base)
    await db_session.flush()

    imported_lead = Lead(
        user_id=owner_ctx.user.id,
        lead_base_id=imported_base.id,
        id_cliente="IMP-DEL",
        nome_cliente="Lead Importado",
    )
    db_session.add(imported_lead)
    await db_session.flush()

    response = await auth_client.delete(f"{BASE}{imported_lead.id}")
    assert response.status_code == 403
    assert response.json()["detail"] == IMPORT_LEAD_DELETE_DETAIL


async def test_leads_delete_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_lead_id(db_session))
    response = await auth_client.delete(f"{BASE}{foreign_id}")
    assert response.status_code == 404
