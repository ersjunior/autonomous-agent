"""Testes unitários — TELEGRAM_MODE e telegram_webhook_url (TUN-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.unit


def test_telegram_webhook_url_with_base() -> None:
    s = Settings.model_construct(
        public_base_url="https://api.example.com",
        telegram_mode="webhook",
    )
    assert (
        s.telegram_webhook_url()
        == "https://api.example.com/api/v1/channels/webhooks/telegram"
    )


def test_telegram_webhook_url_without_base() -> None:
    s = Settings.model_construct(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file="/nonexistent/tunnel_url.txt",
        telegram_mode="webhook",
    )
    assert s.telegram_webhook_url() is None


def test_telegram_webhook_url_from_tunnel_file(tmp_path: Path) -> None:
    url_file = tmp_path / "tunnel_url.txt"
    url_file.write_text("https://abc.trycloudflare.com", encoding="utf-8")
    s = Settings.model_construct(
        public_base_url=None,
        tunnel_mode="temporary",
        tunnel_url_file=str(url_file),
        telegram_mode="webhook",
    )
    assert (
        s.telegram_webhook_url()
        == "https://abc.trycloudflare.com/api/v1/channels/webhooks/telegram"
    )


@pytest.mark.parametrize(
    ("mode", "webhook", "polling"),
    [
        ("polling", False, True),
        ("webhook", True, False),
        ("POLLING", False, True),
        ("WEBHOOK", True, False),
    ],
)
def test_telegram_mode_flags(mode: str, webhook: bool, polling: bool) -> None:
    s = Settings.model_construct(telegram_mode=mode)
    assert s.is_telegram_webhook_mode() is webhook
    assert s.is_telegram_polling_mode() is polling
