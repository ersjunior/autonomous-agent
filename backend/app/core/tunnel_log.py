"""Log da URL pública resolvida no startup (TUN-1)."""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

logger = logging.getLogger("uvicorn.error")


def _emit(message: str) -> None:
    """Garante visibilidade no docker logs (uvicorn --reload isola handlers)."""
    logger.info(message)
    print(message, file=sys.stderr, flush=True)


def log_resolved_public_urls() -> None:
    """Registra PUBLIC_BASE_URL e webhook WhatsApp após bootstrap."""
    base = settings.resolve_public_base_url()
    mode = (settings.tunnel_mode or "temporary").strip().lower()

    if base:
        _emit(f"TUN-1 URL pública resolvida ({mode}): {base}")
        whatsapp = settings.whatsapp_webhook_url()
        if whatsapp:
            _emit(f"TUN-1 Webhook WhatsApp (Twilio Messaging): {whatsapp}")
        if settings.is_telegram_webhook_mode():
            telegram = settings.telegram_webhook_url()
            if telegram:
                _emit(f"TUN-2 Webhook Telegram (setWebhook): {telegram}")
        return

    if mode == "temporary":
        _emit(
            f"TUN-1 URL pública ainda indisponível (TUNNEL_MODE=temporary). "
            f"Aguardando cloudflared gravar {settings.tunnel_url_file}."
        )
        return

    _emit(
        f"TUN-1 PUBLIC_BASE_URL não configurada (TUNNEL_MODE={mode}). "
        "Twilio voz/WhatsApp inbound exigem URL pública."
    )
