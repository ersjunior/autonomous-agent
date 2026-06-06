"""Testes unitários — resolução dinâmica de PUBLIC_BASE_URL (TUN-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.unit


def test_env_url_takes_priority_over_tunnel_file(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://from-tunnel.trycloudflare.com", encoding="utf-8")

    s = Settings(
        public_base_url="https://manual.example.com",
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
    )
    assert s.resolve_public_base_url() == "https://manual.example.com"


def test_temporary_reads_tunnel_file(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://abc-xyz.trycloudflare.com\n", encoding="utf-8")

    s = Settings(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
    )
    assert s.resolve_public_base_url() == "https://abc-xyz.trycloudflare.com"
    assert s.require_public_base_url() == "https://abc-xyz.trycloudflare.com"


def test_temporary_missing_file_returns_none(tmp_path: Path) -> None:
    s = Settings(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(tmp_path / "missing.txt"),
    )
    assert s.resolve_public_base_url() is None


def test_temporary_missing_file_raises_on_require(tmp_path: Path) -> None:
    s = Settings(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(tmp_path / "missing.txt"),
    )
    with pytest.raises(ValueError, match="Aguarde"):
        s.require_public_base_url()


def test_named_without_env_url_returns_none() -> None:
    s = Settings(public_base_url=None, tunnel_mode="named")
    assert s.resolve_public_base_url() is None


def test_whatsapp_webhook_url(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://tunnel.trycloudflare.com", encoding="utf-8")
    s = Settings.model_construct(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
    )
    assert (
        s.whatsapp_webhook_url()
        == "https://tunnel.trycloudflare.com/api/v1/channels/webhooks/whatsapp"
    )
