"""Telegram outbound message helper."""

from telegram import Bot
from telegram.constants import ChatAction

from app.core.config import settings

_TELEGRAM_CHAT_ACTIONS = {
    "typing": ChatAction.TYPING,
    "upload_photo": ChatAction.UPLOAD_PHOTO,
    "record_voice": ChatAction.RECORD_VOICE,
    "upload_voice": ChatAction.UPLOAD_VOICE,
    "upload_document": ChatAction.UPLOAD_DOCUMENT,
    "choose_sticker": ChatAction.CHOOSE_STICKER,
    "find_location": ChatAction.FIND_LOCATION,
}


async def send_telegram_chat_action(chat_id: str, action: str = "typing") -> None:
    """Send a chat action (e.g. typing) via Bot API sendChatAction."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")
    chat_action = _TELEGRAM_CHAT_ACTIONS.get(action, ChatAction.TYPING)
    bot = Bot(token=settings.telegram_bot_token)
    await bot.send_chat_action(chat_id=int(chat_id), action=chat_action)


async def send_telegram_message(chat_id: str, text: str) -> None:
    """Send a proactive message to a Telegram chat."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")
    bot = Bot(token=settings.telegram_bot_token)
    await bot.send_message(chat_id=int(chat_id), text=text)
