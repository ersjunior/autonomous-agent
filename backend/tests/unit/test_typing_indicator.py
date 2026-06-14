"""Testes unitários — channel_typing_indicator (inbound digitando)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agents.channels.typing_indicator import channel_typing_indicator

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_telegram_typing_dispatches_and_cancels_task(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_send_chat_action(chat_id: str, action: str = "typing") -> None:
        calls.append((chat_id, action))

    monkeypatch.setattr(
        "agents.channels.telegram.client.send_telegram_chat_action",
        fake_send_chat_action,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.TYPING_LOOP_INTERVAL_SECONDS",
        0.05,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.telegram_bot_token",
        "test-token",
    )

    async with channel_typing_indicator("telegram", "12345"):
        await asyncio.sleep(0.12)

    assert len(calls) >= 1
    assert calls[0] == ("12345", "typing")


@pytest.mark.asyncio
async def test_whatsapp_typing_calls_indicator_once_with_message_sid(monkeypatch) -> None:
    calls: list[str] = []

    def fake_typing(message_sid: str) -> bool:
        calls.append(message_sid)
        return True

    monkeypatch.setattr(
        "agents.channels.whatsapp.twilio_client.send_whatsapp_typing_indicator",
        fake_typing,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.twilio_account_sid",
        "AC_test",
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.twilio_auth_token",
        "auth_test",
    )

    async with channel_typing_indicator(
        "whatsapp",
        "whatsapp:+5511999999999",
        message_sid="SM_inbound_abc",
    ):
        pass

    assert calls == ["SM_inbound_abc"]


@pytest.mark.asyncio
async def test_whatsapp_without_message_sid_is_noop(monkeypatch) -> None:
    mock_typing = MagicMock()
    monkeypatch.setattr(
        "agents.channels.whatsapp.twilio_client.send_whatsapp_typing_indicator",
        mock_typing,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.twilio_account_sid",
        "AC_test",
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.twilio_auth_token",
        "auth_test",
    )

    async with channel_typing_indicator("whatsapp", "whatsapp:+5511999999999"):
        pass

    mock_typing.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_channel_failure_does_not_propagate(monkeypatch) -> None:
    async def failing_action(chat_id: str, action: str = "typing") -> None:
        raise RuntimeError("Telegram API down")

    monkeypatch.setattr(
        "agents.channels.telegram.client.send_telegram_chat_action",
        failing_action,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.TYPING_LOOP_INTERVAL_SECONDS",
        0.05,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.telegram_bot_token",
        "test-token",
    )

    body_ran = False
    async with channel_typing_indicator("telegram", "99"):
        body_ran = True

    assert body_ran is True


@pytest.mark.asyncio
async def test_whatsapp_indicator_failure_does_not_propagate(monkeypatch) -> None:
    def failing_typing(message_sid: str) -> bool:
        raise RuntimeError("Twilio beta unavailable")

    monkeypatch.setattr(
        "agents.channels.whatsapp.twilio_client.send_whatsapp_typing_indicator",
        failing_typing,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.twilio_account_sid",
        "AC_test",
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.twilio_auth_token",
        "auth_test",
    )

    body_ran = False
    async with channel_typing_indicator(
        "whatsapp",
        "whatsapp:+5511",
        message_sid="SM_fail",
    ):
        body_ran = True

    assert body_ran is True


@pytest.mark.asyncio
async def test_missing_telegram_token_is_noop(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_send(chat_id: str, action: str = "typing") -> None:
        calls.append(chat_id)

    monkeypatch.setattr(
        "agents.channels.telegram.client.send_telegram_chat_action",
        fake_send,
    )
    monkeypatch.setattr(
        "agents.channels.typing_indicator.settings.telegram_bot_token",
        None,
    )

    async with channel_typing_indicator("telegram", "1"):
        pass

    assert calls == []
