"""Extract plain text from KB source files."""

from __future__ import annotations

from pathlib import Path

from app.models.knowledge import KBSourceType


def extract_text_from_file(path: Path, mime_type: str | None, source_type: str) -> str:
    suffix = path.suffix.lower()
    if source_type == KBSourceType.MANUAL.value or suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace").strip()

    if suffix == ".pdf" or (mime_type or "").lower() == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts).strip()

    if suffix == ".docx" or "wordprocessingml" in (mime_type or ""):
        from docx import Document

        doc = Document(str(path))
        parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(parts).strip()

    raise ValueError(f"Formato não suportado para extração: {suffix or mime_type}")
