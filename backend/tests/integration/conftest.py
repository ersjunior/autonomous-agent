"""Conftest local da Camada 2 — hooks que só se aplicam a tests/integration/."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_tabulacao_codigo_cache():
    """Limpa cache de módulo — IDs de transações rollback não podem vazar entre testes."""
    from app.services import tabulacao_assignment as ta

    ta._codigo_id_cache.clear()
    yield
    ta._codigo_id_cache.clear()
