"""Celery task — ingestão assíncrona de documentos KB (extrair → chunk → embed)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal, engine
from app.models.knowledge import KBChunk, KBDocument, KBDocumentStatus
from app.services.kb_chunking import chunk_text
from app.services.kb_text_extract import extract_text_from_file
from agents.services.embedding_service import embed_text
from worker.celery_app import celery

logger = logging.getLogger(__name__)


async def _mark_kb_error(document_id: uuid.UUID, message: str) -> None:
    """Garante status ERROR — nunca deixa documento preso em PROCESSING."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(KBDocument, document_id)
        if doc is None:
            return
        doc.status = KBDocumentStatus.ERROR.value
        doc.error_message = message[:2000]
        doc.chunk_count = 0
        doc.total_chunks_estimated = 0
        doc.chunks_processed = 0
        await session.execute(delete(KBChunk).where(KBChunk.document_id == doc.id))
        await session.commit()


async def _process_kb_document_async(document_id: uuid.UUID) -> None:
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()

    async with AsyncSessionLocal() as session:
        doc = await session.get(KBDocument, document_id)
        if doc is None:
            logger.warning("KB document %s not found; skipping", document_id)
            return

        try:
            doc.chunks_processed = 0
            doc.total_chunks_estimated = 0
            doc.error_message = None
            await session.commit()

            if not doc.file_path:
                raise ValueError("Documento sem file_path")

            path = Path(doc.file_path)
            if not path.is_file():
                raise FileNotFoundError(
                    f"Arquivo não encontrado no volume: {path}. "
                    "Verifique se o worker monta kb_uploads."
                )

            plain = extract_text_from_file(path, doc.mime_type, doc.source_type)
            if not plain.strip():
                raise ValueError("Nenhum texto extraído do documento")

            pieces = chunk_text(plain)
            if not pieces:
                raise ValueError("Chunking não produziu segmentos válidos")

            doc.total_chunks_estimated = len(pieces)
            doc.chunks_processed = 0
            await session.execute(delete(KBChunk).where(KBChunk.document_id == doc.id))
            await session.commit()

            now = datetime.now(timezone.utc)
            doc_id = doc.id
            owner_id = doc.user_id
            for index, content in enumerate(pieces):
                vector = await embed_text(content)
                session.add(
                    KBChunk(
                        document_id=doc_id,
                        owner_user_id=owner_id,
                        chunk_index=index,
                        content=content,
                        embedding=vector,
                        created_at=now,
                    )
                )
                await session.execute(
                    update(KBDocument)
                    .where(KBDocument.id == doc_id)
                    .values(chunks_processed=index + 1)
                )
                await session.commit()

            await session.execute(
                update(KBDocument)
                .where(KBDocument.id == doc_id)
                .values(
                    chunk_count=len(pieces),
                    status=KBDocumentStatus.READY.value,
                    error_message=None,
                )
            )
            await session.commit()

            logger.info(
                "KB document %s ready: %s chunks (owner=%s)",
                doc.id,
                doc.chunk_count,
                doc.user_id,
            )
        except Exception as exc:
            await session.rollback()
            doc = await session.get(KBDocument, document_id)
            if doc is not None:
                doc.status = KBDocumentStatus.ERROR.value
                doc.error_message = str(exc)[:2000]
                doc.chunk_count = 0
                doc.total_chunks_estimated = 0
                doc.chunks_processed = 0
                await session.execute(delete(KBChunk).where(KBChunk.document_id == doc.id))
                await session.commit()
            logger.exception("KB ingestion failed for document %s", document_id)
            raise


def _run_kb_async(document_id: str) -> None:
    async def _wrapper() -> None:
        try:
            await _process_kb_document_async(uuid.UUID(document_id))
        finally:
            await engine.dispose()

    asyncio.run(_wrapper())


@celery.task(bind=True, max_retries=2)
def process_kb_document(self, document_id: str) -> str:
    """Processa um KBDocument: extrai texto, chunk, embed, persiste KBChunks."""
    try:
        _run_kb_async(document_id)
        return document_id
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            try:
                asyncio.run(_mark_kb_error(uuid.UUID(document_id), str(exc)))
            except Exception:
                logger.exception(
                    "Failed to mark KB document %s as ERROR after retries",
                    document_id,
                )
            raise
        raise self.retry(exc=exc, countdown=15) from exc
