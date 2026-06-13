"""Testes unitários — derivação de status do túnel (TUN-3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.schemas.tunnel import HealthProbeSection
from app.services.tunnel_status import (
    derive_tunnel_status,
    get_tunnel_status,
    probe_public_health,
)

pytestmark = pytest.mark.unit


def test_derive_status_aguardando_without_url() -> None:
    assert derive_tunnel_status(None, HealthProbeSection()) == "aguardando"


def test_derive_status_configurado_without_probe() -> None:
    assert (
        derive_tunnel_status(
            "https://example.com",
            HealthProbeSection(),
            run_probe=False,
        )
        == "configurado"
    )


def test_derive_status_verificado_on_probe_ok() -> None:
    probe = HealthProbeSection(attempted=True, ok=True, status_code=200, latency_ms=10)
    assert derive_tunnel_status("https://example.com", probe) == "verificado"


def test_derive_status_inacessivel_on_probe_fail() -> None:
    probe = HealthProbeSection(
        attempted=True,
        ok=False,
        status_code=503,
        latency_ms=10,
        error="HTTP 503",
    )
    assert derive_tunnel_status("https://example.com", probe) == "inacessivel"


def test_probe_public_health_success() -> None:
    class FakeResponse:
        status_code = 200

    probe = probe_public_health(
        "https://tunnel.example.com",
        http_get=lambda _url: FakeResponse(),  # type: ignore[arg-type, return-value]
    )
    assert probe.attempted is True
    assert probe.ok is True
    assert probe.status_code == 200


def test_probe_public_health_failure_without_crash() -> None:
    def _boom(_url: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    probe = probe_public_health("https://dead.example.com", http_get=_boom)
    assert probe.attempted is True
    assert probe.ok is False
    assert probe.error is not None


@pytest.mark.asyncio
async def test_get_tunnel_status_temporary_from_file(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://abc.trycloudflare.com\n", encoding="utf-8")

    cfg = Settings(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
        telegram_mode="polling",
    )

    class FakeResponse:
        status_code = 200

    result = await get_tunnel_status(
        cfg,
        http_get=lambda _url: FakeResponse(),  # type: ignore[arg-type, return-value]
    )

    assert result.status == "verificado"
    assert result.public_base_url_resolved == "https://abc.trycloudflare.com"
    assert result.public_base_url_source == "tunnel_file"
    assert result.whatsapp_webhook_url.endswith("/api/v1/channels/webhooks/whatsapp")
    assert result.telegram_webhook_url is None


@pytest.mark.asyncio
async def test_get_tunnel_status_aguardando_without_url(tmp_path: Path) -> None:
    cfg = Settings(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(tmp_path / "missing.txt"),
        telegram_mode="polling",
    )

    result = await get_tunnel_status(cfg, run_probe=False)

    assert result.status == "aguardando"
    assert result.public_base_url_resolved is None
    assert result.health_probe.attempted is False


@pytest.mark.asyncio
async def test_env_diverges_from_tunnel_file(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://new-tunnel.trycloudflare.com", encoding="utf-8")

    cfg = Settings(
        public_base_url="https://old-stale.example.com",
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
    )

    def _fail_probe(_url: str) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    result = await get_tunnel_status(cfg, http_get=_fail_probe)

    assert result.public_base_url_source == "env"
    assert result.public_base_url_resolved == "https://old-stale.example.com"
    assert result.tunnel_url_file_raw == "https://new-tunnel.trycloudflare.com"
    assert result.env_tunnel_url_diverges is True
    assert result.status == "inacessivel"


@pytest.mark.asyncio
async def test_dead_env_url_inacessivel_without_crash(tmp_path: Path) -> None:
    cfg = Settings(
        public_base_url="https://dead-url.invalid",
        tunnel_mode="named",
        tunnel_url_file=str(tmp_path / "unused.txt"),
    )

    def _fail_probe(_url: str) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    result = await get_tunnel_status(cfg, http_get=_fail_probe)

    assert result.status == "inacessivel"
    assert result.health_probe.ok is False
    assert result.health_probe.error is not None


@pytest.mark.asyncio
async def test_telegram_webhook_mode_exposes_url(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://tunnel.trycloudflare.com", encoding="utf-8")

    cfg = Settings(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
        telegram_mode="webhook",
        telegram_bot_token="123:ABC",
    )

    class FakeResponse:
        status_code = 200

    with patch(
        "app.services.tunnel_status._fetch_telegram_webhook_info",
        new=AsyncMock(return_value=(True, "https://tunnel.trycloudflare.com/api/v1/channels/webhooks/telegram")),
    ):
        result = await get_tunnel_status(
            cfg,
            http_get=lambda _url: FakeResponse(),  # type: ignore[arg-type, return-value]
        )

    assert result.telegram_mode == "webhook"
    assert result.telegram_webhook_url.endswith("/api/v1/channels/webhooks/telegram")
    assert result.telegram_webhook_registered is True
