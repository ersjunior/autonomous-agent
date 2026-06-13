"""Monta status do túnel e webhooks com health probe honesto (TUN-3)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import httpx
from telegram import Bot

from app.core.config import Settings, settings
from app.schemas.tunnel import HealthProbeSection, TunnelStatusResponse

logger = logging.getLogger(__name__)

_HEALTH_PROBE_TIMEOUT_SECONDS = 5.0


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    stripped = url.strip().rstrip("/")
    return stripped or None


def _read_tunnel_file_metadata(tunnel_url_file: str) -> tuple[bool, str | None]:
    path = Path(tunnel_url_file)
    if not path.is_file():
        return False, None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return True, None
    return True, raw.rstrip("/")


def _resolve_public_base_url_source(
    env_url: str | None,
    tunnel_mode: str,
    file_raw: str | None,
) -> str | None:
    if env_url:
        return "env"
    mode = (tunnel_mode or "temporary").strip().lower()
    if mode == "temporary" and file_raw:
        return "tunnel_file"
    return None


def probe_public_health(
    base_url: str,
    *,
    timeout: float = _HEALTH_PROBE_TIMEOUT_SECONDS,
    http_get: Callable[[str], httpx.Response] | None = None,
) -> HealthProbeSection:
    """GET {base}/health — nunca propaga exceção."""
    url = f"{base_url.rstrip('/')}/health"
    started = time.perf_counter()

    def _default_get(target: str) -> httpx.Response:
        with httpx.Client(timeout=timeout) as client:
            return client.get(target)

    getter = http_get or _default_get

    try:
        response = getter(url)
        latency_ms = int((time.perf_counter() - started) * 1000)
        ok = 200 <= response.status_code < 300
        return HealthProbeSection(
            attempted=True,
            ok=ok,
            status_code=response.status_code,
            latency_ms=latency_ms,
            error=None if ok else f"HTTP {response.status_code}",
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.debug("Health probe falhou para %s: %s", url, exc)
        return HealthProbeSection(
            attempted=True,
            ok=False,
            status_code=None,
            latency_ms=latency_ms,
            error=str(exc),
        )


def derive_tunnel_status(
    public_base_url_resolved: str | None,
    health_probe: HealthProbeSection,
    *,
    run_probe: bool = True,
) -> str:
    if not public_base_url_resolved:
        return "aguardando"
    if not run_probe or not health_probe.attempted:
        return "configurado"
    if health_probe.ok:
        return "verificado"
    return "inacessivel"


async def _fetch_telegram_webhook_info(
    cfg: Settings,
) -> tuple[bool | None, str | None]:
    if not cfg.is_telegram_webhook_mode():
        return None, None

    token = (cfg.telegram_bot_token or "").strip()
    if not token:
        return None, None

    try:
        bot = Bot(token=token)
        info = await bot.get_webhook_info()
        registered_url = _normalize_url(info.url)
        expected = cfg.telegram_webhook_url()
        if not registered_url:
            return False, None
        if expected:
            return registered_url == expected, registered_url
        return True, registered_url
    except Exception as exc:
        logger.debug("getWebhookInfo indisponível: %s", exc)
        return None, None


async def get_tunnel_status(
    cfg: Settings | None = None,
    *,
    run_probe: bool = True,
    http_get: Callable[[str], httpx.Response] | None = None,
) -> TunnelStatusResponse:
    """Payload completo para GET /api/v1/tunnel/status."""
    cfg = cfg or settings

    tunnel_mode = (cfg.tunnel_mode or "temporary").strip().lower()
    telegram_mode = (cfg.telegram_mode or "polling").strip().lower()
    env_url = _normalize_url(cfg.public_base_url)
    file_exists, file_raw = _read_tunnel_file_metadata(cfg.tunnel_url_file)
    resolved = _normalize_url(cfg.resolve_public_base_url())
    source = _resolve_public_base_url_source(env_url, tunnel_mode, file_raw)

    env_tunnel_url_diverges = bool(
        source == "env"
        and file_raw
        and env_url
        and env_url != file_raw,
    )

    health_probe = HealthProbeSection()
    if resolved and run_probe:
        health_probe = probe_public_health(resolved, http_get=http_get)

    status = derive_tunnel_status(resolved, health_probe, run_probe=run_probe)

    whatsapp_webhook_url = cfg.whatsapp_webhook_url() if resolved else None
    telegram_webhook_url = (
        cfg.telegram_webhook_url()
        if cfg.is_telegram_webhook_mode() and resolved
        else None
    )

    telegram_webhook_registered: bool | None = None
    telegram_webhook_registered_url: str | None = None
    if cfg.is_telegram_webhook_mode():
        telegram_webhook_registered, telegram_webhook_registered_url = (
            await _fetch_telegram_webhook_info(cfg)
        )

    return TunnelStatusResponse(
        tunnel_mode=tunnel_mode,
        telegram_mode=telegram_mode,
        public_base_url_resolved=resolved,
        public_base_url_source=source,
        public_base_url_env=env_url,
        tunnel_url_file=cfg.tunnel_url_file,
        tunnel_url_file_exists=file_exists,
        tunnel_url_file_raw=file_raw,
        env_tunnel_url_diverges=env_tunnel_url_diverges,
        whatsapp_webhook_url=whatsapp_webhook_url,
        telegram_webhook_url=telegram_webhook_url,
        telegram_webhook_registered=telegram_webhook_registered,
        telegram_webhook_registered_url=telegram_webhook_registered_url,
        status=status,
        health_probe=health_probe,
    )
