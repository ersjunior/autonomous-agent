"""Testes unitários — chunking KB (KB-1)."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.kb_chunking import chunk_text

pytestmark = pytest.mark.unit


@pytest.fixture
def chunk_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tamanhos determinísticos — não depende do .env."""
    monkeypatch.setattr(settings, "kb_chunk_size", 100)
    monkeypatch.setattr(settings, "kb_chunk_overlap", 10)


def _repeat(char: str, count: int) -> str:
    return char * count


def test_empty_text_returns_empty_list() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk(chunk_params: None) -> None:
    text = _repeat("x", 250)
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_text_shorter_than_min_chars_returns_whole_text(chunk_params: None) -> None:
    """Abaixo de ~200 chars filtra chunks; fallback devolve o texto inteiro."""
    text = _repeat("a", 150)
    chunks = chunk_text(text)
    assert chunks == [text]


def test_long_text_multiple_chunks_respect_target_size(chunk_params: None) -> None:
    target = settings.kb_chunk_size * 4
    text = _repeat("b", 900)
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= target for c in chunks)


def test_consecutive_chunks_share_overlap(chunk_params: None) -> None:
    overlap = settings.kb_chunk_overlap * 4
    text = _repeat("c", 900)
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        assert chunks[i][-overlap:] == chunks[i + 1][:overlap]


def test_exact_chunk_size_single_chunk(chunk_params: None) -> None:
    target = settings.kb_chunk_size * 4
    text = _repeat("d", target)
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert len(chunks[0]) == target


def test_small_chunk_size_with_long_paragraph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "kb_chunk_size", 60)
    monkeypatch.setattr(settings, "kb_chunk_overlap", 8)
    target = 60 * 4
    text = _repeat("e", target * 3)
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= target for c in chunks)


def test_paragraph_boundaries_preserved_when_small(chunk_params: None) -> None:
    para1 = _repeat("p", 120)
    para2 = _repeat("q", 120)
    text = f"{para1}\n\n{para2}"
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert para1 in chunks[0]
    assert para2 in chunks[0]
