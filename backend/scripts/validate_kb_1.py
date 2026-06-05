#!/usr/bin/env python3
"""Validação KB-1 — ingestão assíncrona, chunks pgvector, CRUD e volume."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import func, select, text

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.knowledge import KBChunk, KBDocument, KBDocumentStatus, KBSourceType
from app.models.user import User
from app.services.kb_chunking import chunk_text
from app.services.kb_storage import delete_document_files, save_manual_text, save_upload_file
from worker.tasks.kb_ingestion import _process_kb_document_async


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    status = "OK" if cond else "FALHA"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond


async def test_schema() -> bool:
    print("\n=== Schema (migration + índices) ===")
    async with AsyncSessionLocal() as session:
        tables = (
            await session.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname='public' AND tablename IN ('kb_documents','kb_chunks')"
                )
            )
        ).scalars().all()
        hnsw = (
            await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename='kb_chunks' AND indexname='ix_kb_chunks_embedding'"
                )
            )
        ).scalar_one_or_none()
        dim = (
            await session.execute(
                text(
                    "SELECT format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                    "WHERE c.relname='kb_chunks' AND a.attname='embedding'"
                )
            )
        ).scalar_one_or_none()
        expected_dim = settings.embedding_dimensions
        dim_ok = dim == f"vector({expected_dim})"
        return (
            _ok("tabelas kb_documents + kb_chunks", set(tables) == {"kb_documents", "kb_chunks"})
            and _ok("índice HNSW ix_kb_chunks_embedding", hnsw == "ix_kb_chunks_embedding")
            and _ok(f"embedding dim={expected_dim}", dim_ok, f"atttypmod={dim}")
        )


async def _admin_user(session) -> User:
    return (
        await session.execute(select(User).where(User.email == "admin@admin.com"))
    ).scalar_one()


async def _wait_ready(session, doc_id: uuid.UUID, timeout: float = 120.0) -> KBDocument | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = await session.get(KBDocument, doc_id)
        if doc and doc.status in (KBDocumentStatus.READY.value, KBDocumentStatus.ERROR.value):
            return doc
        await asyncio.sleep(1.0)
        session.expire_all()
    return await session.get(KBDocument, doc_id)


async def _chunk_stats(session, doc_id: uuid.UUID) -> tuple[int, int | None]:
    count = (
        await session.execute(
            select(func.count()).select_from(KBChunk).where(KBChunk.document_id == doc_id)
        )
    ).scalar_one()
    sample_dim = (
        await session.execute(
            text(
                "SELECT vector_dims(embedding) FROM kb_chunks "
                "WHERE document_id = :doc_id LIMIT 1"
            ),
            {"doc_id": str(doc_id)},
        )
    ).scalar_one_or_none()
    return int(count), sample_dim


async def _ingest_doc(session, doc: KBDocument) -> KBDocument:
    doc_id = doc.id
    await session.commit()
    await _process_kb_document_async(doc_id)
    session.expire_all()
    return await session.get(KBDocument, doc_id)


async def test_txt_upload(session, user_id: uuid.UUID) -> tuple[bool, uuid.UUID | None]:
    print("\n=== Upload TXT → READY + embedding 768 ===")
    doc_id = uuid.uuid4()
    content = "Política de devolução: prazo de 30 dias.\n\nProdutos eletrônicos exigem nota fiscal."
    dest, name, mime = save_upload_file(
        user_id, doc_id, content.encode("utf-8"), "policy.txt", "text/plain"
    )
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title="Policy TXT",
        source_type=KBSourceType.UPLOAD.value,
        filename=name,
        mime_type=mime,
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    session.add(doc)
    doc = await _ingest_doc(session, doc)
    chunk_count, dim = await _chunk_stats(session, doc.id)
    ok = (
        _ok("status READY", doc.status == KBDocumentStatus.READY.value, doc.status)
        and _ok("chunk_count > 0", doc.chunk_count > 0, str(doc.chunk_count))
        and _ok("KBChunks persistidos", chunk_count == doc.chunk_count, str(chunk_count))
        and _ok("embedding dim 768", dim == settings.embedding_dimensions, str(dim))
        and _ok("arquivo no volume", Path(doc.file_path).is_file())
    )
    return ok, doc.id


def _minimal_pdf_bytes(text: str) -> bytes:
    """Gera PDF mínimo legível por pypdf (content stream Type1 Helvetica)."""
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET"
    stream_bytes = stream.encode("latin-1")
    objects: list[bytes] = []
    xref_offsets: list[int] = []

    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream_bytes)} >>stream\n".encode("ascii")
        + stream_bytes
        + b"\nendstream endobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    body = b"%PDF-1.4\n"
    for obj in objects:
        xref_offsets.append(len(body))
        body += obj

    xref_pos = len(body)
    body += b"xref\n0 6\n"
    body += b"0000000000 65535 f \n"
    for off in xref_offsets:
        body += f"{off:010d} 00000 n \n".encode("ascii")
    body += b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n"
    body += f"{xref_pos}\n%%EOF\n".encode("ascii")
    return body


async def test_pdf_upload(session, user_id: uuid.UUID) -> bool:
    print("\n=== Upload PDF → extração + READY ===")
    doc_id = uuid.uuid4()
    pdf_bytes = _minimal_pdf_bytes("Manual PDF KB1 teste de extração.")
    dest, name, mime = save_upload_file(
        user_id, doc_id, pdf_bytes, "manual.pdf", "application/pdf"
    )
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title="Manual PDF",
        source_type=KBSourceType.UPLOAD.value,
        filename=name,
        mime_type=mime,
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    session.add(doc)
    doc = await _ingest_doc(session, doc)
    return _ok(
        "PDF READY com chunks",
        doc.status == KBDocumentStatus.READY.value and doc.chunk_count > 0,
        f"status={doc.status} chunks={doc.chunk_count} err={doc.error_message}",
    )


async def test_manual(session, user_id: uuid.UUID) -> bool:
    print("\n=== Texto manual → MANUAL + READY ===")
    doc_id = uuid.uuid4()
    body = "FAQ: horário de atendimento das 9h às 18h em dias úteis."
    dest = save_manual_text(user_id, doc_id, body)
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title="FAQ Horário",
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    session.add(doc)
    doc = await _ingest_doc(session, doc)
    return (
        _ok("source_type MANUAL", doc.source_type == KBSourceType.MANUAL.value)
        and _ok("manual READY", doc.status == KBDocumentStatus.READY.value and doc.chunk_count > 0)
    )


async def test_multi_chunk(session, user_id: uuid.UUID) -> bool:
    print("\n=== Chunking multi-segmento (overlap) ===")
    para = "Parágrafo extenso sobre políticas internas e procedimentos operacionais. " * 40
    long_text = (para + "\n\n") * 8
    pieces = chunk_text(long_text)
    doc_id = uuid.uuid4()
    dest = save_manual_text(user_id, doc_id, long_text)
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title="Doc longo",
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    session.add(doc)
    doc = await _ingest_doc(session, doc)
    return (
        _ok("chunker local >1", len(pieces) > 1, str(len(pieces)))
        and _ok("ingestão >1 chunks", doc.chunk_count > 1, str(doc.chunk_count))
    )


async def test_delete(session, user_id: uuid.UUID, doc_id: uuid.UUID | None) -> bool:
    print("\n=== DELETE cascade + arquivo ===")
    if doc_id is None:
        return _ok("doc para delete", False, "sem doc_id")
    doc = await session.get(KBDocument, doc_id)
    if doc is None:
        return _ok("documento existe", False)
    file_path = doc.file_path
    chunks_before = (
        await session.execute(select(func.count()).select_from(KBChunk).where(KBChunk.document_id == doc_id))
    ).scalar_one()
    await session.delete(doc)
    await session.commit()
    delete_document_files(file_path)
    remaining_chunks = (
        await session.execute(select(func.count()).select_from(KBChunk).where(KBChunk.document_id == doc_id))
    ).scalar_one()
    file_gone = not Path(file_path).is_file() if file_path else True
    return (
        _ok("chunks antes >0", int(chunks_before) > 0, str(chunks_before))
        and _ok("cascade remove chunks", int(remaining_chunks) == 0)
        and _ok("arquivo removido", file_gone)
    )


async def test_is_system_delete_forbidden(session, user_id: uuid.UUID) -> bool:
    print("\n=== is_system → DELETE bloqueado (403) ===")
    from app.core.authorization import raise_if_cannot_delete
    from fastapi import HTTPException

    doc_id = uuid.uuid4()
    dest = save_manual_text(user_id, doc_id, "Documento institucional.")
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title="Institucional",
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path=str(dest),
        status=KBDocumentStatus.READY.value,
        is_system=True,
        chunk_count=0,
    )
    session.add(doc)
    await session.commit()

    blocked = False
    try:
        raise_if_cannot_delete(doc, User(id=user_id, email="x", hashed_password="", full_name=""))
    except HTTPException as exc:
        blocked = exc.status_code == 403
    await session.delete(doc)
    await session.commit()
    delete_document_files(str(dest))
    return _ok("DELETE is_system → 403", blocked)


async def test_worker_no_interface_error(session, user_id: uuid.UUID) -> bool:
    print("\n=== Worker ingestão sem InterfaceError ===")
    doc_id = uuid.uuid4()
    dest = save_manual_text(user_id, doc_id, "Smoke worker KB sem InterfaceError.")
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title="Worker smoke",
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    session.add(doc)
    try:
        doc = await _ingest_doc(session, doc)
        ok = doc.status == KBDocumentStatus.READY.value
        detail = doc.error_message or "ok"
    except Exception as exc:
        ok = False
        detail = str(exc)
        if "InterfaceError" in detail:
            detail = "InterfaceError detectado"
    finally:
        fresh = await session.get(KBDocument, doc_id)
        if fresh:
            fp = fresh.file_path
            await session.delete(fresh)
            await session.commit()
            delete_document_files(fp)
    return _ok("sem InterfaceError", ok, detail)


async def main() -> int:
    print("Validação KB-1 — ingestão e catálogo")
    results: list[bool] = []

    async with AsyncSessionLocal() as session:
        user = await _admin_user(session)
        user_id = user.id
        results.append(await test_schema())
        txt_ok, txt_id = await test_txt_upload(session, user_id)
        results.append(txt_ok)
        results.append(await test_pdf_upload(session, user_id))
        results.append(await test_manual(session, user_id))
        results.append(await test_multi_chunk(session, user_id))
        results.append(await test_delete(session, user_id, txt_id))
        results.append(await test_is_system_delete_forbidden(session, user_id))
        results.append(await test_worker_no_interface_error(session, user_id))

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 50}")
    print(f"Resultado: {passed}/{total} cenários OK")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
