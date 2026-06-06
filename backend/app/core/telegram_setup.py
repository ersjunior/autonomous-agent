"""Configuração do Bot Telegram no startup (TUN-2): setWebhook / deleteWebhook."""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram import Bot, Update

from app.core.config import settings

logger = logging.getLogger("uvicorn.error")

_RETRY_INTERVAL_SECONDS = 5
_RETRY_MAX_ATTEMPTS = 60  # ~5 minutos


def _emit(message: str) -> None:
    logger.info(message)
    print(message, file=sys.stderr, flush=True)


async def _delete_webhook(bot: Bot) -> None:
    try:
        ok = await bot.delete_webhook(drop_pending_updates=True)
        _emit(f"TUN-2 Telegram polling: deleteWebhook ok={ok}")
    except Exception as exc:
        _emit(f"TUN-2 Telegram deleteWebhook falhou (não fatal): {exc}")


async def _set_webhook_once(bot: Bot, url: str) -> bool:
    try:
        ok = await bot.set_webhook(
            url=url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        _emit(f"TUN-2 Telegram webhook registrado: {url} (ok={ok})")
        info = await bot.get_webhook_info()
        _emit(f"TUN-2 getWebhookInfo: url={info.url!r} pending={info.pending_update_count}")
        return bool(ok)
    except Exception as exc:
        _emit(f"TUN-2 setWebhook falhou para {url}: {exc}")
        return False


async def _retry_set_webhook(bot: Bot) -> None:
    """Aguarda PUBLIC_BASE_URL (TUN-1) e registra webhook sem bloquear o startup."""
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        url = settings.telegram_webhook_url()
        if url:
            if await _set_webhook_once(bot, url):
                return
        else:
            _emit(
                f"TUN-2 aguardando URL pública para setWebhook "
                f"(tentativa {attempt}/{_RETRY_MAX_ATTEMPTS})"
            )
        await asyncio.sleep(_RETRY_INTERVAL_SECONDS)

    _emit(
        "TUN-2 setWebhook não concluído após retries — "
        "verifique PUBLIC_BASE_URL / cloudflared e reinicie o backend."
    )


async def configure_telegram_on_startup() -> None:
    """
    Aplica modo TELEGRAM_MODE na API do Telegram.

    - polling: deleteWebhook (evita 409 com getUpdates).
    - webhook: setWebhook com retry em background se URL ainda indisponível.
    """
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return

    mode = (settings.telegram_mode or "polling").strip().lower()
    bot = Bot(token=token)

    if mode == "polling":
        await _delete_webhook(bot)
        _emit(
            "TUN-2 TELEGRAM_MODE=polling — inicie o polling separadamente "
            "(profile telegram-polling ou docker exec manual). "
            "NÃO rode polling com webhook ativo."
        )
        return

    if mode == "webhook":
        url = settings.telegram_webhook_url()
        if url:
            await _set_webhook_once(bot, url)
        else:
            _emit(
                "TUN-2 TELEGRAM_MODE=webhook — URL pública indisponível; "
                "retry assíncrono de setWebhook iniciado."
            )
            asyncio.create_task(_retry_set_webhook(bot))
        return

    _emit(f"TUN-2 TELEGRAM_MODE inválido: {mode!r} (use polling ou webhook)")
