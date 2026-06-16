"""Unit tests — inactivity sweep WhatsApp template retomada (W3 fase 3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.inactivity_text import INACTIVITY_WARNING_MESSAGE
from app.services.whatsapp_outbound import WhatsAppSendMode
from worker.tasks.inactivity_sweep import _send_inactivity_warning

pytestmark = pytest.mark.unit

_RETOMADA_SID = "HXfebf2d00b102badb36d5e81c12a0b050"
_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _record(*, last_inbound: datetime | None = None) -> MagicMock:
    rec = MagicMock()
    rec.data_ultimo_contato = last_inbound
    return rec


def _lead(name: str = "Eliezer Ramos Silveira Junior") -> MagicMock:
    lead = MagicMock()
    lead.nome_cliente = name
    return lead


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SMretomada")
@patch("worker.tasks.inactivity_sweep.resolve_whatsapp_send_mode")
async def test_inactivity_warning_whatsapp_uses_retomada_outside_24h(
    resolve_mock,
    send_mock,
) -> None:
    resolve_mock.return_value = WhatsAppSendMode(
        mode="template",
        content_sid=_RETOMADA_SID,
        content_variables={"1": "Eliezer Ramos Silveira Junior"},
    )

    sid = await _send_inactivity_warning(
        "whatsapp",
        "+5511999999999",
        INACTIVITY_WARNING_MESSAGE,
        record=_record(last_inbound=None),
        lead=_lead(),
    )

    assert sid == "SMretomada"
    send_mock.assert_called_once_with(
        "+5511999999999",
        content_sid=_RETOMADA_SID,
        content_variables={"1": "Eliezer Ramos Silveira Junior"},
    )


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SMfree")
@patch("worker.tasks.inactivity_sweep.resolve_whatsapp_send_mode")
async def test_inactivity_warning_whatsapp_freeform_within_24h(
    resolve_mock,
    send_mock,
) -> None:
    resolve_mock.return_value = WhatsAppSendMode(mode="freeform")

    sid = await _send_inactivity_warning(
        "whatsapp",
        "+5511999999999",
        INACTIVITY_WARNING_MESSAGE,
        record=_record(last_inbound=_NOW - timedelta(hours=2)),
        lead=_lead(),
    )

    assert sid == "SMfree"
    send_mock.assert_called_once_with("+5511999999999", INACTIVITY_WARNING_MESSAGE)


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SMfree")
@patch("worker.tasks.inactivity_sweep.resolve_whatsapp_send_mode")
async def test_inactivity_warning_whatsapp_freeform_when_templates_off(
    resolve_mock,
    send_mock,
) -> None:
    resolve_mock.return_value = WhatsAppSendMode(mode="freeform")

    sid = await _send_inactivity_warning(
        "whatsapp",
        "+5511999999999",
        INACTIVITY_WARNING_MESSAGE,
        record=_record(last_inbound=None),
        lead=_lead(),
    )

    assert sid == "SMfree"
    send_mock.assert_called_once_with("+5511999999999", INACTIVITY_WARNING_MESSAGE)


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_telegram_message")
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message")
async def test_inactivity_warning_telegram_unchanged(
    send_whatsapp_mock,
    send_telegram_mock,
) -> None:
    send_telegram_mock.return_value = None

    sid = await _send_inactivity_warning(
        "telegram",
        "5043259127",
        INACTIVITY_WARNING_MESSAGE,
        record=_record(),
        lead=_lead(),
    )

    assert sid is None
    send_whatsapp_mock.assert_not_called()
    send_telegram_mock.assert_awaited_once_with("5043259127", INACTIVITY_WARNING_MESSAGE)
