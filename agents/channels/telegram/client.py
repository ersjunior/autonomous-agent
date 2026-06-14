"""Telegram outbound message helper."""

from pathlib import Path

from telegram import Bot
from telegram.constants import ChatAction

from app.core.config import settings

_TELEGRAM_CHAT_ACTIONS = {
    "typing": ChatAction.TYPING,
    "upload_photo": ChatAction.UPLOAD_PHOTO,
    "record_video": ChatAction.RECORD_VIDEO,
    "upload_video": ChatAction.UPLOAD_VIDEO,
    "record_voice": ChatAction.RECORD_VOICE,
    "upload_voice": ChatAction.UPLOAD_VOICE,
    "upload_document": ChatAction.UPLOAD_DOCUMENT,
    "choose_sticker": ChatAction.CHOOSE_STICKER,
    "find_location": ChatAction.FIND_LOCATION,
    "record_video_note": ChatAction.RECORD_VIDEO_NOTE,
    "upload_video_note": ChatAction.UPLOAD_VIDEO_NOTE,
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


async def send_telegram_video(
    chat_id: str,
    video_path: str,
    caption: str = "",
) -> None:
    """Send an MP4 video to a Telegram chat (Bot API sendVideo)."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")

    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Vídeo não encontrado: {path}")

    bot = Bot(token=settings.telegram_bot_token)
    caption_text = (caption or "").strip() or None
    with path.open("rb") as video_file:
        await bot.send_video(
            chat_id=int(chat_id),
            video=video_file,
            caption=caption_text,
        )
