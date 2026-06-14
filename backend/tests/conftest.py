"""Fixtures compartilhadas — Camadas 2 (integração) e 3 (API)."""

from __future__ import annotations

import pytest

pytest_plugins = ["tests.db_fixtures"]


@pytest.fixture
def sao_paulo_tz() -> str:
    """Fuso padrão do motor de acionamento."""
    return "America/Sao_Paulo"
