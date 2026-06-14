"""Inbound typing indicators — Telegram loop + WhatsApp single-shot (Twilio beta)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import settings

logger = logging.getLogger(__name__)

TYPING_LOOP_INTERVAL_SECONDS = 4.0


async def _telegram_typing_loop(chat_id: str) -> None:
    from agents.channels.telegram.client import send_telegram_chat_action

    while True:
        try:
            await send_telegram_chat_action(chat_id, action="typing")
        except Exception:
            logger.warning(
                "Falha ao enviar typing indicator Telegram chat_id=%s",
                chat_id,
                exc_info=True,
            )
        await asyncio.sleep(TYPING_LOOP_INTERVAL_SECONDS)


@asynccontextmanager
async def channel_typing_indicator(
    channel: str,
    user_id: str,
    *,
    message_sid: str | None = None,
) -> AsyncIterator[None]:
    """
    Show "typing..." while the inbound worker processes route_message.

    Telegram: re-sends sendChatAction every ~4s until the context exits.
    WhatsApp: single POST to Twilio (needs message_sid; lasts up to ~25s).
    Failures are logged and never propagate to the caller.
    """
    ch = (channel or "").lower().strip()
    task: asyncio.Task | None = None

    try:
        if ch == "telegram" and settings.telegram_bot_token:
            task = asyncio.create_task(_telegram_typing_loop(user_id))
        elif ch == "whatsapp":
            sid = (message_sid or "").strip()
            if sid and settings.twilio_account_sid and settings.twilio_auth_token:
                from agents.channels.whatsapp.twilio_client import (
                    send_whatsapp_typing_indicator,
                )

                send_whatsapp_typing_indicator(sid)
    except Exception:
        logger.warning(
            "Falha ao iniciar typing indicator channel=%s user_id=%s",
            ch,
            user_id,
            exc_info=True,
        )

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
