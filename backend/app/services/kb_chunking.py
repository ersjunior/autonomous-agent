"""
Chunking para ingestão KB (KB-1).

Estratégia:
  - Aproximação de tokens: ~4 caracteres por token (PT).
  - Tamanho alvo e overlap vêm de settings (default 512 / 64 tokens).
  - Primeiro divide por parágrafos (\\n\\n); parágrafos grandes são subdivididos
    por tamanho fixo com overlap.
  - Descarta chunks menores que ~50 tokens (~200 chars).
"""

from __future__ import annotations

from app.core.config import settings

_CHARS_PER_TOKEN = 4
_MIN_TOKENS = 50


def _target_chars() -> int:
    return settings.kb_chunk_size * _CHARS_PER_TOKEN


def _overlap_chars() -> int:
    return settings.kb_chunk_overlap * _CHARS_PER_TOKEN


def _min_chars() -> int:
    return _MIN_TOKENS * _CHARS_PER_TOKEN


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_text(text: str) -> list[str]:
    """Retorna lista ordenada de chunks de texto."""
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    target = _target_chars()
    overlap = _overlap_chars()
    min_chars = _min_chars()

    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    raw_chunks: list[str] = []
    buffer = ""

    for para in paragraphs:
        if len(para) > target:
            if buffer.strip():
                raw_chunks.extend(_split_long_text(buffer.strip(), target, overlap))
                buffer = ""
            raw_chunks.extend(_split_long_text(para, target, overlap))
            continue

        candidate = f"{buffer}\n\n{para}".strip() if buffer else para
        if len(candidate) <= target:
            buffer = candidate
        else:
            if buffer.strip():
                raw_chunks.extend(_split_long_text(buffer.strip(), target, overlap))
            buffer = para

    if buffer.strip():
        raw_chunks.extend(_split_long_text(buffer.strip(), target, overlap))

    filtered = [c for c in raw_chunks if len(c) >= min_chars]
    if filtered:
        return filtered
    if normalized:
        return [normalized]
    return []
