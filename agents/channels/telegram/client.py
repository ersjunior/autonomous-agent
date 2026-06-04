"""Telegram outbound message helper."""

from pathlib import Path

from telegram import Bot

from app.core.config import settings


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
