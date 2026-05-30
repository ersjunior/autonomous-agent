"""Telegram outbound message helper."""

from telegram import Bot

from app.core.config import settings


async def send_telegram_message(chat_id: str, text: str) -> None:
    """Send a proactive message to a Telegram chat."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")
    bot = Bot(token=settings.telegram_bot_token)
    await bot.send_message(chat_id=int(chat_id), text=text)
