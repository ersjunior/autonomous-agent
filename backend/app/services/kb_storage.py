"""Persist KB upload files on shared volume."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import settings

ALLOWED_KB_EXTENSIONS = frozenset({".pdf", ".docx", ".txt"})
ALLOWED_KB_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "application/octet-stream",
    }
)


def kb_uploads_root() -> Path:
    root = Path(settings.kb_uploads_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext == ".doc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use .docx (Word moderno). Formato .doc não suportado.",
        )
    if ext not in ALLOWED_KB_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Extensão inválida. Use .pdf, .docx ou .txt",
        )
    return ext


def document_storage_dir(owner_user_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    path = kb_uploads_root() / str(owner_user_id) / str(document_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload_file(
    owner_user_id: uuid.UUID,
    document_id: uuid.UUID,
    raw: bytes,
    filename: str,
    content_type: str | None,
) -> tuple[Path, str, str]:
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio")
    if len(raw) > settings.kb_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo excede {settings.kb_max_upload_bytes // (1024 * 1024)}MB",
        )

    ext = _normalize_extension(filename)
    if content_type and content_type not in ALLOWED_KB_CONTENT_TYPES:
        if not content_type.startswith("text/") and content_type != "application/pdf":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Type não suportado para base de conhecimento",
            )

    dest_dir = document_storage_dir(owner_user_id, document_id)
    safe_name = f"original{ext}"
    dest = dest_dir / safe_name
    dest.write_bytes(raw)

    mime = content_type or {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
    }.get(ext, "application/octet-stream")

    return dest, filename, mime


def save_manual_text(
    owner_user_id: uuid.UUID,
    document_id: uuid.UUID,
    content: str,
) -> Path:
    text = (content or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conteúdo vazio")
    dest_dir = document_storage_dir(owner_user_id, document_id)
    dest = dest_dir / "manual.txt"
    dest.write_text(text, encoding="utf-8")
    return dest


def delete_document_files(file_path: str | None) -> None:
    if not file_path:
        return
    path = Path(file_path)
    if path.is_file():
        path.unlink(missing_ok=True)
    parent = path.parent
    if parent.is_dir() and parent != kb_uploads_root():
        try:
            parent.rmdir()
        except OSError:
            pass
        grand = parent.parent
        if grand.is_dir() and grand != kb_uploads_root():
            try:
                grand.rmdir()
            except OSError:
                pass
