"""Camada 3 — workspace institutional identity API (GET/PUT /settings/identity)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.api

BASE = "/api/v1/settings/identity"

SAMPLE_IDENTITY = {
    "company_name": "Acme Corp",
    "display_name": "Acme Educação",
    "tone": "formal e acolhedor",
    "business_context": "Plataforma de cursos online para profissionais.",
    "greeting_hint": "Cumprimente pelo nome quando souber.",
}


async def test_identity_get_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_identity_get_empty_when_missing(auth_client) -> None:
    response = await auth_client.get(BASE)
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "company_name": None,
        "display_name": None,
        "tone": None,
        "business_context": None,
        "greeting_hint": None,
    }


async def test_identity_put_persists_and_get_returns(auth_client) -> None:
    put = await auth_client.put(BASE, json=SAMPLE_IDENTITY)
    assert put.status_code == 200
    assert put.json()["company_name"] == SAMPLE_IDENTITY["company_name"]
    assert put.json()["display_name"] == SAMPLE_IDENTITY["display_name"]

    get = await auth_client.get(BASE)
    assert get.status_code == 200
    assert get.json() == put.json()


async def test_identity_put_upsert_updates(auth_client) -> None:
    await auth_client.put(BASE, json=SAMPLE_IDENTITY)

    updated = {
        **SAMPLE_IDENTITY,
        "company_name": "Acme Atualizada",
        "tone": "descontraído",
    }
    put = await auth_client.put(BASE, json=updated)
    assert put.status_code == 200
    assert put.json()["company_name"] == "Acme Atualizada"
    assert put.json()["tone"] == "descontraído"
    assert put.json()["display_name"] == SAMPLE_IDENTITY["display_name"]

    get = await auth_client.get(BASE)
    assert get.json()["company_name"] == "Acme Atualizada"


async def test_identity_put_empty_strings_treated_as_absence(auth_client) -> None:
    await auth_client.put(BASE, json=SAMPLE_IDENTITY)

    cleared = {
        "company_name": "Acme Corp",
        "display_name": "",
        "tone": "   ",
        "business_context": SAMPLE_IDENTITY["business_context"],
        "greeting_hint": None,
    }
    put = await auth_client.put(BASE, json=cleared)
    assert put.status_code == 200
    body = put.json()
    assert body["company_name"] == "Acme Corp"
    assert body["display_name"] is None
    assert body["tone"] is None
    assert body["greeting_hint"] is None


async def test_identity_isolation_between_users(
    client,
    owner_ctx,
    second_owner,
) -> None:
    from app.core.security import create_access_token

    token_a = create_access_token(
        data={"sub": str(owner_ctx.user.id), "email": owner_ctx.user.email},
    )
    token_b = create_access_token(
        data={"sub": str(second_owner.id), "email": second_owner.email},
    )
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    put_a = await client.put(BASE, json=SAMPLE_IDENTITY, headers=headers_a)
    assert put_a.status_code == 200

    get_b = await client.get(BASE, headers=headers_b)
    assert get_b.status_code == 200
    assert get_b.json()["company_name"] is None

    foreign_payload = {"company_name": "Empresa do Usuário B"}
    put_b = await client.put(BASE, json=foreign_payload, headers=headers_b)
    assert put_b.status_code == 200
    assert put_b.json()["company_name"] == "Empresa do Usuário B"

    get_a = await client.get(BASE, headers=headers_a)
    assert get_a.json()["company_name"] == SAMPLE_IDENTITY["company_name"]
