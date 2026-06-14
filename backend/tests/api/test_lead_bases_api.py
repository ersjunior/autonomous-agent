"""Camada 3 — lead-bases: CRUD, import CSV multipart e devolutiva."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.authorization import SYSTEM_RECORD_EDIT_DETAIL
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from tests.api.ownership_helpers import foreign_lead_base_id, foreign_owner_context
from tests.integration.helpers import add_campaign_channel

pytestmark = pytest.mark.api

BASE = "/api/v1/lead-bases/"
TODAY = date.today().isoformat()


def _create_payload(campaign_id: str, *, channels: list[str] | None = None) -> dict:
    return {
        "campaign_id": campaign_id,
        "data_recebimento": TODAY,
        "channel_types": channels if channels is not None else ["whatsapp"],
        "column_mapping": {"aux1": "Obs"},
    }


def _valid_csv_bytes() -> bytes:
    content = (
        "nome,telefone\n"
        "João Import,5511999887766\n"
        "Maria Import,5511888776655\n"
    )
    return content.encode("utf-8")


async def _ensure_campaign_channels(db_session, owner_ctx) -> None:
    await add_campaign_channel(db_session, owner_ctx.campaign.id, "whatsapp")


async def test_lead_bases_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_lead_bases_list_returns_paginated_shape(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)

    response = await auth_client.get(BASE)
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert body["skip"] == 0
    assert body["limit"] == 50
    assert isinstance(body["items"], list)
    assert body["total"] >= 1


@pytest.mark.parametrize(
    "query,expected_detail",
    [
        ("skip=-1", "skip must be >= 0"),
        ("limit=0", "limit must be between 1 and 200"),
        ("limit=201", "limit must be between 1 and 200"),
    ],
)
async def test_lead_bases_list_invalid_pagination_returns_400(
    auth_client,
    query: str,
    expected_detail: str,
) -> None:
    response = await auth_client.get(f"{BASE}?{query}")
    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


async def test_lead_bases_create_returns_201_and_persists(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)
    payload = _create_payload(str(owner_ctx.campaign.id))

    response = await auth_client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["campaign_id"] == str(owner_ctx.campaign.id)
    assert body["channel_types"] == ["whatsapp"]
    assert body["leads_count"] == 0
    # _to_lead_base_response não popula source — schema default é MANUAL (enum).
    assert body["source"] == "MANUAL"

    persisted = await db_session.get(LeadBase, uuid.UUID(body["id"]))
    assert persisted is not None


async def test_lead_bases_create_empty_channel_types_returns_422(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.post(
        BASE,
        json=_create_payload(str(owner_ctx.campaign.id), channels=[]),
    )
    assert response.status_code == 422


async def test_lead_bases_create_channels_not_in_campaign_returns_400(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)
    response = await auth_client.post(
        BASE,
        json=_create_payload(str(owner_ctx.campaign.id), channels=["telegram"]),
    )
    assert response.status_code == 400
    assert "Channel types not in campaign" in response.json()["detail"]


async def test_lead_bases_create_foreign_campaign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_ctx = await foreign_owner_context(db_session, suffix="lb-campaign-404")
    response = await auth_client.post(
        BASE,
        json=_create_payload(str(foreign_ctx.campaign.id)),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Campaign not found"


async def test_lead_bases_import_csv_returns_201_with_leads(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)

    response = await auth_client.post(
        f"{BASE}import",
        data={
            "campaign_id": str(owner_ctx.campaign.id),
            "data_recebimento": TODAY,
            "channel_types": "whatsapp",
        },
        files={"file": ("leads.csv", _valid_csv_bytes(), "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    # DB grava IMPORT; response_model omite source e cai no default MANUAL (ver divergência).
    assert body["leads_count"] == 2

    count = await db_session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.lead_base_id == uuid.UUID(body["id"]))
    )
    assert count == 2


async def test_lead_bases_import_empty_csv_returns_400(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)

    response = await auth_client.post(
        f"{BASE}import",
        data={
            "campaign_id": str(owner_ctx.campaign.id),
            "data_recebimento": TODAY,
            "channel_types": "whatsapp",
        },
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CSV file is empty"


async def test_lead_bases_import_invalid_encoding_returns_400(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)

    response = await auth_client.post(
        f"{BASE}import",
        data={
            "campaign_id": str(owner_ctx.campaign.id),
            "data_recebimento": TODAY,
            "channel_types": "whatsapp",
        },
        files={"file": ("bad.csv", b"\xff\xfe\x00", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CSV must be UTF-8 encoded"


async def test_lead_bases_patch_column_mapping_returns_200(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)
    create = await auth_client.post(BASE, json=_create_payload(str(owner_ctx.campaign.id)))
    base_id = create.json()["id"]

    response = await auth_client.patch(
        f"{BASE}{base_id}/column-mapping",
        json={"column_mapping": {"aux1": "Campo A", "aux2": "Campo B"}},
    )
    assert response.status_code == 200
    assert response.json()["column_mapping"] == {"aux1": "Campo A", "aux2": "Campo B"}


async def test_lead_bases_patch_system_returns_403(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    owner_ctx.lead_base.is_system = True
    await db_session.flush()

    response = await auth_client.patch(
        f"{BASE}{owner_ctx.lead_base.id}/column-mapping",
        json={"column_mapping": {"aux1": "X"}},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_EDIT_DETAIL


async def test_lead_bases_patch_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_lead_base_id(db_session))
    response = await auth_client.patch(
        f"{BASE}{foreign_id}/column-mapping",
        json={"column_mapping": {"aux1": "X"}},
    )
    assert response.status_code == 404


async def test_lead_bases_delete_returns_204(auth_client, owner_ctx, db_session) -> None:
    await _ensure_campaign_channels(db_session, owner_ctx)
    create = await auth_client.post(BASE, json=_create_payload(str(owner_ctx.campaign.id)))
    base_id = create.json()["id"]

    response = await auth_client.delete(f"{BASE}{base_id}")
    assert response.status_code == 204
    assert await db_session.get(LeadBase, uuid.UUID(base_id)) is None


async def test_lead_bases_delete_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_lead_base_id(db_session))
    response = await auth_client.delete(f"{BASE}{foreign_id}")
    assert response.status_code == 404


async def test_lead_bases_metrics_returns_200(auth_client, owner_ctx) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.lead_base.id}/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "total_leads" in body
    assert "taxa_conversao" in body
    assert "por_status" in body


async def test_lead_bases_metrics_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_lead_base_id(db_session))
    response = await auth_client.get(f"{BASE}{foreign_id}/metrics")
    assert response.status_code == 404


async def test_lead_bases_list_leads_returns_paginated(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.lead_base.id}/leads")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert len(body["items"]) >= 1
    assert body["items"][0]["lead_base_id"] == str(owner_ctx.lead_base.id)


async def test_lead_bases_devolutiva_returns_xlsx_stream(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.lead_base.id}/devolutiva")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in response.headers.get("content-disposition", "")
    assert len(response.content) > 0


async def test_lead_bases_list_devolutivas_returns_200(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(f"{BASE}{owner_ctx.lead_base.id}/devolutivas")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_lead_bases_historical_devolutiva_missing_returns_404(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(
        f"{BASE}{owner_ctx.lead_base.id}/devolutivas/2020-01-01"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Devolutiva not found"
