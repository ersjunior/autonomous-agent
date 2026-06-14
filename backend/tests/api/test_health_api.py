"""Camada 3 — smoke do /health via AsyncClient."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.api


async def test_health_returns_200_without_auth(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "service" in body
