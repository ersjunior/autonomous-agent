"""Knowledge base CRUD and upload API (KB-1)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import raise_if_cannot_delete, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.knowledge import KBDocument, KBDocumentStatus, KBSourceType
from app.models.user import User
from app.schemas.knowledge import KBDocumentResponse, KBManualCreate
from app.services.kb_storage import delete_document_files, save_manual_text, save_upload_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def _get_document(
    document_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> KBDocument:
    result = await db.execute(select(KBDocument).where(KBDocument.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento não encontrado")
    raise_if_cannot_view(doc, user, not_found_detail="Documento não encontrado")
    return doc


def _enqueue_processing(document_id: uuid.UUID) -> None:
    from worker.tasks.kb_ingestion import process_kb_document

    process_kb_document.delay(str(document_id))


@router.get("/", response_model=list[KBDocumentResponse])
async def list_knowledge_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KBDocument]:
    result = await db.execute(
        select(KBDocument).where(
            or_(KBDocument.is_system.is_(True), KBDocument.user_id == user.id)
        ).order_by(KBDocument.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/upload",
    response_model=KBDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KBDocument:
    raw = await file.read()
    doc_id = uuid.uuid4()
    dest, original_name, mime = save_upload_file(
        user.id,
        doc_id,
        raw,
        file.filename or "document.txt",
        file.content_type,
    )

    doc = KBDocument(
        id=doc_id,
        user_id=user.id,
        title=(title or original_name or "Documento").strip()[:255],
        source_type=KBSourceType.UPLOAD.value,
        filename=original_name,
        mime_type=mime,
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    _enqueue_processing(doc.id)
    logger.info("KB upload queued doc=%s user=%s file=%s", doc.id, user.email, original_name)
    return doc


@router.post(
    "/manual",
    response_model=KBDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_manual_knowledge_document(
    payload: KBManualCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KBDocument:
    doc_id = uuid.uuid4()
    dest = save_manual_text(user.id, doc_id, payload.content)

    doc = KBDocument(
        id=doc_id,
        user_id=user.id,
        title=payload.title.strip(),
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=False,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    _enqueue_processing(doc.id)
    logger.info("KB manual queued doc=%s user=%s", doc.id, user.email)
    return doc


@router.get("/{document_id}", response_model=KBDocumentResponse)
async def get_knowledge_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KBDocument:
    return await _get_document(document_id, user, db)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    doc = await _get_document(document_id, user, db)
    raise_if_cannot_delete(doc, user)
    file_path = doc.file_path
    await db.delete(doc)
    await db.commit()
    delete_document_files(file_path)
