"""Camada 3 — CRUD + ownership de /tabulacoes via API."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.authorization import SYSTEM_RECORD_DELETE_DETAIL, SYSTEM_RECORD_EDIT_DETAIL
from app.core.seed import SEED_TABULACAO_CODIGOS
from app.models.tabulacao import Tabulacao
from tests.api.ownership_helpers import foreign_tabulacao_id

pytestmark = pytest.mark.api

BASE = "/api/v1/tabulacoes/"


def _tabulacao_payload(*, suffix: str | None = None, codigo: str | None = None) -> dict:
    tag = suffix or uuid.uuid4().hex[:8]
    return {
        "nome": f"Tabulação {tag}",
        "codigo": codigo or f"CUSTOM:API:{tag.upper()}",
        "categoria": "CUSTOMIZADO",
        "is_terminal": False,
        "descricao": "Teste API",
    }


async def _system_tabulacao_id(db_session) -> uuid.UUID:
    result = await db_session.execute(
        select(Tabulacao).where(Tabulacao.is_system.is_(True)).limit(1)
    )
    tab = result.scalar_one()
    return tab.id


async def test_tabulacoes_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_tabulacoes_list_includes_system_and_owner_excludes_foreign(
    auth_client,
    seeded_catalog,
    db_session,
) -> None:
    own = await auth_client.post(BASE, json=_tabulacao_payload(suffix="own-list"))
    assert own.status_code == 201
    own_id = own.json()["id"]

    foreign_id = str(await foreign_tabulacao_id(db_session))
    system_id = str(await _system_tabulacao_id(db_session))

    response = await auth_client.get(BASE)
    assert response.status_code == 200

    ids = {item["id"] for item in response.json()}
    assert own_id in ids
    assert system_id in ids
    assert foreign_id not in ids


async def test_tabulacoes_catalog_returns_visible_items(
    auth_client,
    seeded_catalog,
    db_session,
) -> None:
    response = await auth_client.get(f"{BASE}catalog")
    assert response.status_code == 200

    items = response.json()
    assert isinstance(items, list)
    assert len(items) >= len(SEED_TABULACAO_CODIGOS)

    codigos = {item["codigo"] for item in items}
    assert "NEG:SUCESSO" in codigos or any(c.startswith("NEG:") for c in codigos)
    assert all("nome" in item and "is_terminal" in item for item in items)


async def test_tabulacoes_create_returns_201_and_persists(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    payload = _tabulacao_payload()
    response = await auth_client.post(BASE, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["nome"] == payload["nome"]
    assert body["codigo"] == payload["codigo"]
    assert body["categoria"] == "CUSTOMIZADO"
    assert body["is_system"] is False
    assert body["user_id"] == str(owner_ctx.user.id)

    persisted = await db_session.get(Tabulacao, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.user_id == owner_ctx.user.id


async def test_tabulacoes_create_duplicate_codigo_returns_409(
    auth_client,
    seeded_catalog,
) -> None:
    duplicate_code = next(c for c in SEED_TABULACAO_CODIGOS if c.startswith("NEG:"))
    response = await auth_client.post(
        BASE,
        json=_tabulacao_payload(codigo=duplicate_code),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Código de tabulação já existe"


@pytest.mark.parametrize(
    "payload",
    [
        {"codigo": "X", "categoria": "CUSTOMIZADO"},
        {"nome": "Sem categoria", "codigo": "X"},
        {"nome": "Cat inválida", "codigo": "X", "categoria": "INVALIDA"},
    ],
)
async def test_tabulacoes_create_invalid_payload_returns_422(
    auth_client,
    payload: dict,
) -> None:
    response = await auth_client.post(BASE, json=payload)
    assert response.status_code == 422


async def test_tabulacoes_get_own_returns_200(auth_client) -> None:
    create = await auth_client.post(BASE, json=_tabulacao_payload(suffix="get-own"))
    tab_id = create.json()["id"]

    response = await auth_client.get(f"{BASE}{tab_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tab_id


async def test_tabulacoes_get_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_tabulacao_id(db_session))
    response = await auth_client.get(f"{BASE}{foreign_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Tabulação not found"


async def test_tabulacoes_get_missing_returns_404(auth_client) -> None:
    response = await auth_client.get(f"{BASE}{uuid.uuid4()}")
    assert response.status_code == 404


async def test_tabulacoes_update_own_returns_200(auth_client) -> None:
    create = await auth_client.post(BASE, json=_tabulacao_payload(suffix="upd-own"))
    tab_id = create.json()["id"]

    response = await auth_client.put(
        f"{BASE}{tab_id}",
        json={"nome": "Tabulação Atualizada"},
    )
    assert response.status_code == 200
    assert response.json()["nome"] == "Tabulação Atualizada"


async def test_tabulacoes_update_system_returns_403(
    auth_client,
    seeded_catalog,
    db_session,
) -> None:
    system_id = await _system_tabulacao_id(db_session)
    response = await auth_client.put(
        f"{BASE}{system_id}",
        json={"nome": "Tentativa System"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_EDIT_DETAIL


async def test_tabulacoes_update_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_tabulacao_id(db_session))
    response = await auth_client.put(
        f"{BASE}{foreign_id}",
        json={"nome": "Não deve alterar"},
    )
    assert response.status_code == 404


async def test_tabulacoes_delete_own_returns_204(auth_client, db_session) -> None:
    create = await auth_client.post(BASE, json=_tabulacao_payload(suffix="del-own"))
    tab_id = create.json()["id"]

    response = await auth_client.delete(f"{BASE}{tab_id}")
    assert response.status_code == 204
    assert await db_session.get(Tabulacao, uuid.UUID(tab_id)) is None


async def test_tabulacoes_delete_system_returns_403(
    auth_client,
    seeded_catalog,
    db_session,
) -> None:
    system_id = await _system_tabulacao_id(db_session)
    response = await auth_client.delete(f"{BASE}{system_id}")
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_DELETE_DETAIL


async def test_tabulacoes_delete_foreign_returns_404(auth_client, db_session) -> None:
    foreign_id = str(await foreign_tabulacao_id(db_session))
    response = await auth_client.delete(f"{BASE}{foreign_id}")
    assert response.status_code == 404
