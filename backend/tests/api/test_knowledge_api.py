"""Camada 3 — knowledge API: list, upload, manual, get, delete + ownership."""

from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import select

from app.core.authorization import SYSTEM_RECORD_DELETE_DETAIL
from app.models.knowledge import KBDocument, KBDocumentStatus, KBSourceType
from tests.api.ownership_helpers import foreign_owner_context
from tests.integration.helpers import OwnerContext, get_admin_user

pytestmark = pytest.mark.api

BASE = "/api/v1/knowledge/"


@pytest.fixture
def mock_kb_pipeline(monkeypatch, tmp_path):
    """Evita Celery real; grava arquivos em tmp_path."""
    state: dict = {"delay_calls": []}

    def fake_delay(document_id: str) -> None:
        state["delay_calls"].append(document_id)

    monkeypatch.setattr(
        "worker.tasks.kb_ingestion.process_kb_document.delay",
        fake_delay,
    )

    def fake_save_upload(owner_user_id, doc_id, raw, filename, content_type):
        dest = tmp_path / str(owner_user_id) / str(doc_id) / (filename or "upload.txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        mime = content_type or "text/plain"
        return dest, filename or "upload.txt", mime

    def fake_save_manual(owner_user_id, doc_id, content):
        dest = tmp_path / str(owner_user_id) / str(doc_id) / "manual.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest

    monkeypatch.setattr("app.api.v1.knowledge.save_upload_file", fake_save_upload)
    monkeypatch.setattr("app.api.v1.knowledge.save_manual_text", fake_save_manual)
    monkeypatch.setattr("app.api.v1.knowledge.delete_document_files", lambda _path: None)
    return state


async def _create_kb_doc(
    db_session,
    owner_ctx: OwnerContext,
    *,
    title: str = "Doc privado",
) -> KBDocument:
    doc = KBDocument(
        user_id=owner_ctx.user.id,
        title=title,
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path="/tmp/manual.txt",
        status=KBDocumentStatus.READY.value,
        is_system=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


# --- list ---


async def test_knowledge_list_requires_auth(client) -> None:
    response = await client.get(BASE)
    assert response.status_code == 401


async def test_knowledge_list_includes_owner_and_system_excludes_foreign(
    auth_client,
    owner_ctx,
    system_seeds,
    db_session,
) -> None:
    own = await _create_kb_doc(db_session, owner_ctx, title="Meu doc")
    admin = await get_admin_user(db_session)
    system_doc = KBDocument(
        user_id=admin.id,
        title="Doc institucional",
        source_type=KBSourceType.MANUAL.value,
        status=KBDocumentStatus.READY.value,
        is_system=True,
        chunk_count=0,
    )
    db_session.add(system_doc)
    foreign_ctx = await foreign_owner_context(db_session, suffix="kb-foreign")
    foreign_doc = await _create_kb_doc(db_session, foreign_ctx, title="Doc estrangeiro")
    await db_session.flush()

    response = await auth_client.get(BASE)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert str(own.id) in ids
    assert str(system_doc.id) in ids
    assert str(foreign_doc.id) not in ids


# --- upload ---


async def test_knowledge_upload_returns_202_and_queues_processing(
    auth_client,
    owner_ctx,
    db_session,
    mock_kb_pipeline,
) -> None:
    content = b"Conteudo de teste da base de conhecimento."
    response = await auth_client.post(
        f"{BASE}upload",
        files={"file": ("teste.txt", io.BytesIO(content), "text/plain")},
        data={"title": "Upload API test"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == KBDocumentStatus.PROCESSING.value
    assert body["source_type"] == KBSourceType.UPLOAD.value
    assert body["title"] == "Upload API test"
    assert body["user_id"] == str(owner_ctx.user.id)
    assert len(mock_kb_pipeline["delay_calls"]) == 1
    assert mock_kb_pipeline["delay_calls"][0] == str(body["id"])

    persisted = await db_session.get(KBDocument, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.status == KBDocumentStatus.PROCESSING.value


# --- manual ---


async def test_knowledge_manual_returns_202_and_queues_processing(
    auth_client,
    owner_ctx,
    db_session,
    mock_kb_pipeline,
) -> None:
    payload = {"title": "Manual API", "content": "Texto manual para chunking."}
    response = await auth_client.post(f"{BASE}manual", json=payload)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == KBDocumentStatus.PROCESSING.value
    assert body["source_type"] == KBSourceType.MANUAL.value
    assert body["title"] == "Manual API"
    assert len(mock_kb_pipeline["delay_calls"]) == 1

    persisted = await db_session.get(KBDocument, uuid.UUID(body["id"]))
    assert persisted is not None
    assert persisted.status == KBDocumentStatus.PROCESSING.value


# --- get / delete ---


async def test_knowledge_get_own_returns_200(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    doc = await _create_kb_doc(db_session, owner_ctx)
    response = await auth_client.get(f"{BASE}{doc.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(doc.id)


async def test_knowledge_get_foreign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_ctx = await foreign_owner_context(db_session, suffix="kb-get")
    doc = await _create_kb_doc(db_session, foreign_ctx)
    response = await auth_client.get(f"{BASE}{doc.id}")
    assert response.status_code == 404


async def test_knowledge_delete_own_returns_204(
    auth_client,
    owner_ctx,
    db_session,
    mock_kb_pipeline,
) -> None:
    doc = await _create_kb_doc(db_session, owner_ctx)
    response = await auth_client.delete(f"{BASE}{doc.id}")
    assert response.status_code == 204
    assert await db_session.get(KBDocument, doc.id) is None


async def test_knowledge_delete_system_returns_403(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    admin = await get_admin_user(db_session)
    doc = KBDocument(
        user_id=admin.id,
        title="System KB",
        source_type=KBSourceType.MANUAL.value,
        status=KBDocumentStatus.READY.value,
        is_system=True,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()

    response = await auth_client.delete(f"{BASE}{doc.id}")
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_DELETE_DETAIL


async def test_knowledge_delete_foreign_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_ctx = await foreign_owner_context(db_session, suffix="kb-del")
    doc = await _create_kb_doc(db_session, foreign_ctx)
    response = await auth_client.delete(f"{BASE}{doc.id}")
    assert response.status_code == 404
    assert await db_session.get(KBDocument, doc.id) is not None
