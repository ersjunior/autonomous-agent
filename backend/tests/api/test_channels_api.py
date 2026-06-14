"""Camada 3 — CRUD + ownership de /channels via API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.authorization import SYSTEM_RECORD_DELETE_DETAIL, SYSTEM_RECORD_EDIT_DETAIL
from app.models.channel import Channel
from tests.api.ownership_helpers import foreign_channel_id
from tests.integration.helpers import get_admin_user

pytestmark = pytest.mark.api

BASE = "/api/v1/channels/"


def _channel_payload(*, suffix: str | None = None) -> dict:
    tag = suffix or uuid.uuid4().hex[:8]
    return {
        "name": f"Channel_{tag}",
        "type": "WHATSAPP",
        "credentials": {"sid": "test"},
        "is_active": True,
    }


async def _system_channel_id(db_session) -> uuid.UUID:
    admin = await get_admin_user(db_session)
    channel = (
        await db_session.execute(
            select(Channel).where(
                Channel.user_id == admin.id,
                Channel.name == "WhatsApp_Agent",
            )
        )
    ).scalar_one()
    return channel.id


async def test_channels_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_channels_list_includes_owner_and_system_excludes_foreign(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    foreign_id = str(await foreign_channel_id(db_session))
    system_id = str(await _system_channel_id(db_session))

    response = await auth_client.get(BASE)
    assert response.status_code == 200

    ids = {item["id"] for item in response.json()}
    assert system_id in ids
    assert foreign_id not in ids


async def test_channels_create_returns_201_and_persists(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    payload = _channel_payload()
    response = await auth_client.post(BASE, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == payload["name"]
    assert body["type"] == "WHATSAPP"
    assert body["is_system"] is False
    assert body["is_active"] is True

    persisted = await db_session.get(Channel, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.user_id == owner_ctx.user.id


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Sem tipo"},
        {"type": "NOT_A_CHANNEL"},
    ],
)
async def test_channels_create_invalid_payload_returns_422(
    auth_client,
    payload: dict,
) -> None:
    response = await auth_client.post(BASE, json=payload)
    assert response.status_code == 422


async def test_channels_get_own_via_create(auth_client, db_session) -> None:
    create = await auth_client.post(BASE, json=_channel_payload())
    channel_id = create.json()["id"]

    response = await auth_client.get(f"{BASE}{channel_id}")
    assert response.status_code == 200
    assert response.json()["id"] == channel_id


async def test_channels_get_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_channel_id(db_session))
    response = await auth_client.get(f"{BASE}{foreign_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Channel not found"


async def test_channels_get_missing_returns_404(auth_client) -> None:
    response = await auth_client.get(f"{BASE}{uuid.uuid4()}")
    assert response.status_code == 404


async def test_channels_update_own_returns_200(auth_client) -> None:
    create = await auth_client.post(BASE, json=_channel_payload())
    channel_id = create.json()["id"]

    response = await auth_client.put(
        f"{BASE}{channel_id}",
        json={"name": "Canal Atualizado", "is_active": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Canal Atualizado"
    assert body["is_active"] is False


async def test_channels_update_system_returns_403(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    system_id = await _system_channel_id(db_session)
    response = await auth_client.put(
        f"{BASE}{system_id}",
        json={"name": "Tentativa System"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_EDIT_DETAIL


async def test_channels_update_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_channel_id(db_session))
    response = await auth_client.put(
        f"{BASE}{foreign_id}",
        json={"name": "Não deve alterar"},
    )
    assert response.status_code == 404


async def test_channels_delete_own_returns_204(auth_client, db_session) -> None:
    create = await auth_client.post(BASE, json=_channel_payload())
    channel_id = create.json()["id"]

    response = await auth_client.delete(f"{BASE}{channel_id}")
    assert response.status_code == 204
    assert await db_session.get(Channel, uuid.UUID(channel_id)) is None


async def test_channels_delete_system_returns_403(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    system_id = await _system_channel_id(db_session)
    response = await auth_client.delete(f"{BASE}{system_id}")
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_DELETE_DETAIL


async def test_channels_delete_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_channel_id(db_session))
    response = await auth_client.delete(f"{BASE}{foreign_id}")
    assert response.status_code == 404
