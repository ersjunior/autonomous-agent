"""Telegram bot handler — enfileira inbound no Celery (R-A.0).

Modos (TELEGRAM_MODE):
  - polling: ``TelegramHandler.start()`` → ``run_polling`` (processo separado).
  - webhook: ``process_webhook_update`` → ``Application.process_update`` → ``handle_message``.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

_webhook_application: Application | None = None
_webhook_app_initialized = False


def enqueue_telegram_inbound(chat_id: str, text: str) -> None:
    """Enfileira mensagem inbound Telegram no Celery (ponto único polling + webhook)."""
    cid = (chat_id or "").strip()
    body = (text or "").strip()
    if not cid or not body:
        return

    from worker.tasks.inbound_handler import process_inbound_message

    process_inbound_message.delay("telegram", cid, body)
    logger.info("Telegram inbound enfileirado chat_id=%s", cid)


class TelegramHandler:
    def __init__(self, token: str) -> None:
        self.application = Application.builder().token(token).build()
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not update.message or not update.message.text or not update.effective_chat:
            return

        chat_id = str(update.effective_chat.id)
        text = update.message.text.strip()
        enqueue_telegram_inbound(chat_id, text)

    def start(self) -> None:
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    def stop(self) -> None:
        if self.application.running:
            self.application.stop_running()


async def _get_webhook_application(token: str) -> Application:
    """Application singleton inicializada para processar updates via webhook."""
    global _webhook_application, _webhook_app_initialized

    if _webhook_application is None:
        _webhook_application = TelegramHandler(token).application

    if not _webhook_app_initialized:
        await _webhook_application.initialize()
        _webhook_app_initialized = True

    return _webhook_application


async def process_webhook_update(data: dict[str, Any], token: str) -> None:
    """Processa Update JSON do POST webhook (reusa handlers → handle_message → enqueue)."""
    application = await _get_webhook_application(token)
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
