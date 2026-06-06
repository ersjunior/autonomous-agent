"""Fixtures compartilhadas — crescerá nas camadas 2 (integração) e 3 (e2e)."""

from __future__ import annotations

import pytest


@pytest.fixture
def sao_paulo_tz() -> str:
    """Fuso padrão do motor de acionamento."""
    return "America/Sao_Paulo"
