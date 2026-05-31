"""Telegram bot handler wired to the LangGraph orchestrator."""

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agents.orchestrator.router import route_message


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
        if not update.message or not update.message.text or not update.effective_user:
            return

        result = await route_message(
            update.message.text,
            "telegram",
            str(update.effective_user.id),
        )
        response_text = result.get("response", "")
        if response_text:
            await update.message.reply_text(response_text)

    def start(self) -> None:
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    def stop(self) -> None:
        if self.application.running:
            self.application.stop_running()
