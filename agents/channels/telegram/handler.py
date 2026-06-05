"""Telegram bot handler — enfileira inbound no Celery (R-A.0).

Polling recebe updates; cada mensagem de texto dispara ``process_inbound_message``.
O worker envia a resposta via ``send_telegram_message`` (API ativa).
"""

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)


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
        if not text:
            return

        from worker.tasks.inbound_handler import process_inbound_message

        process_inbound_message.delay("telegram", chat_id, text)
        logger.info("Telegram inbound enfileirado chat_id=%s", chat_id)

    def start(self) -> None:
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    def stop(self) -> None:
        if self.application.running:
            self.application.stop_running()
