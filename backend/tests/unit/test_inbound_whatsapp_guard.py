"""Unit tests — guard inbound WhatsApp fora da janela 24h (W3 fase 3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.whatsapp_outbound import WhatsAppSendMode
from worker.tasks.inbound_handler import _deliver_inbound_response

pytestmark = pytest.mark.unit

_RETOMADA_SID = "HXfebf2d00b102badb36d5e81c12a0b050"
_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _record(*, last_inbound: datetime | None) -> MagicMock:
    rec = MagicMock()
    rec.data_ultimo_contato = last_inbound
    return rec


def _lead() -> MagicMock:
    lead = MagicMock()
    lead.id = "lead-uuid"
    lead.nome_cliente = "José da Silva"
    return lead


@pytest.mark.asyncio
@patch("agents.channels.whatsapp.twilio_client.send_whatsapp_message", return_value="SMfree")
@patch("worker.tasks.inbound_handler.settings")
async def test_inbound_within_24h_uses_freeform_llm_text(
    settings_mock,
    send_mock,
) -> None:
    settings_mock.twilio_account_sid = "ACtest"
    settings_mock.twilio_auth_token = "token"
    settings_mock.twilio_phone_number = "+551150399542"
    settings_mock.whatsapp_templates_enabled.return_value = True

    ok = await _deliver_inbound_response(
        "whatsapp",
        "+5511999999999",
        "Resposta do LLM aqui",
        lead=_lead(),
        record=_record(last_inbound=_NOW - timedelta(hours=1)),
    )

    assert ok is True
    send_mock.assert_called_once_with("+5511999999999", "Resposta do LLM aqui")


@pytest.mark.asyncio
@patch("agents.channels.whatsapp.twilio_client.send_whatsapp_message", return_value="SMretomada")
@patch("worker.tasks.inbound_handler.resolve_whatsapp_send_mode")
@patch("worker.tasks.inbound_handler.settings")
async def test_inbound_outside_24h_uses_retomada_template(
    settings_mock,
    resolve_mock,
    send_mock,
) -> None:
    settings_mock.twilio_account_sid = "ACtest"
    settings_mock.twilio_auth_token = "token"
    settings_mock.twilio_phone_number = "+551150399542"
    settings_mock.whatsapp_templates_enabled.return_value = True
    resolve_mock.return_value = WhatsAppSendMode(
        mode="template",
        content_sid=_RETOMADA_SID,
        content_variables={"1": "José da Silva"},
    )
    record = _record(last_inbound=_NOW - timedelta(hours=30))

    ok = await _deliver_inbound_response(
        "whatsapp",
        "+5511999999999",
        "Resposta do LLM que não deve ir",
        lead=_lead(),
        record=record,
    )

    assert ok is True
    send_mock.assert_called_once_with(
        "+5511999999999",
        content_sid=_RETOMADA_SID,
        content_variables={"1": "José da Silva"},
    )
    assert record.twilio_message_sid == "SMretomada"
    assert record.last_delivery_status == "queued"


@pytest.mark.asyncio
@patch("agents.channels.whatsapp.twilio_client.send_whatsapp_message")
@patch("worker.tasks.inbound_handler.resolve_whatsapp_send_mode")
@patch("worker.tasks.inbound_handler.settings")
async def test_inbound_outside_24h_blocks_when_no_template(
    settings_mock,
    resolve_mock,
    send_mock,
) -> None:
    settings_mock.twilio_account_sid = "ACtest"
    settings_mock.twilio_auth_token = "token"
    settings_mock.twilio_phone_number = "+551150399542"
    settings_mock.whatsapp_templates_enabled.return_value = True
    resolve_mock.return_value = WhatsAppSendMode(mode="freeform")

    ok = await _deliver_inbound_response(
        "whatsapp",
        "+5511999999999",
        "Resposta bloqueada",
        lead=_lead(),
        record=_record(last_inbound=_NOW - timedelta(hours=30)),
    )

    assert ok is False
    send_mock.assert_not_called()


@pytest.mark.asyncio
@patch("agents.channels.whatsapp.twilio_client.send_whatsapp_message", return_value="SMfree")
@patch("worker.tasks.inbound_handler.settings")
async def test_inbound_outside_24h_freeform_when_templates_off(
    settings_mock,
    send_mock,
) -> None:
    settings_mock.twilio_account_sid = "ACtest"
    settings_mock.twilio_auth_token = "token"
    settings_mock.twilio_phone_number = "+551150399542"
    settings_mock.whatsapp_templates_enabled.return_value = False

    ok = await _deliver_inbound_response(
        "whatsapp",
        "+5511999999999",
        "Texto legado",
        lead=_lead(),
        record=_record(last_inbound=_NOW - timedelta(hours=30)),
    )

    assert ok is True
    send_mock.assert_called_once_with("+5511999999999", "Texto legado")
