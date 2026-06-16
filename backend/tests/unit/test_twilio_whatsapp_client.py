"""Unit tests — Twilio WhatsApp client (freeform + Content Templates)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agents.channels.whatsapp.twilio_client import (
    encode_content_variables,
    send_whatsapp_message,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def twilio_mocks():
    message = MagicMock()
    message.sid = "SMtest999"
    message.status = "queued"
    create_mock = MagicMock(return_value=message)
    client = MagicMock()
    client.messages.create = create_mock
    with (
        patch(
            "agents.channels.whatsapp.twilio_client.Client",
            return_value=client,
        ),
        patch(
            "agents.channels.whatsapp.twilio_client.settings.twilio_account_sid",
            "ACtest",
        ),
        patch(
            "agents.channels.whatsapp.twilio_client.settings.twilio_auth_token",
            "token",
        ),
        patch(
            "agents.channels.whatsapp.twilio_client.settings.twilio_phone_number",
            "+551150399542",
        ),
        patch(
            "agents.channels.whatsapp.twilio_client._whatsapp_status_callback_url",
            return_value="https://example.com/status",
        ),
    ):
        yield create_mock


def test_send_whatsapp_message_freeform_uses_body(twilio_mocks) -> None:
    sid = send_whatsapp_message("+5511999999999", "Olá mundo")

    assert sid == "SMtest999"
    kwargs = twilio_mocks.call_args.kwargs
    assert kwargs["body"] == "Olá mundo"
    assert "content_sid" not in kwargs
    assert kwargs["status_callback"] == "https://example.com/status"
    assert kwargs["to"] == "whatsapp:+5511999999999"


def test_send_whatsapp_message_template_uses_content_sid(twilio_mocks) -> None:
    sid = send_whatsapp_message(
        "+5511999999999",
        content_sid="HX564c9577120a14f2d7d5517c2e26982b",
        content_variables={"1": "Maria"},
    )

    assert sid == "SMtest999"
    kwargs = twilio_mocks.call_args.kwargs
    assert "body" not in kwargs
    assert kwargs["content_sid"] == "HX564c9577120a14f2d7d5517c2e26982b"
    assert kwargs["content_variables"] == json.dumps({"1": "Maria"})


def test_send_whatsapp_message_rejects_both_body_and_template() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        send_whatsapp_message(
            "+5511999999999",
            "texto",
            content_sid="HXabc",
        )


def test_send_whatsapp_message_rejects_neither_body_nor_template() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        send_whatsapp_message("+5511999999999")


def test_send_whatsapp_message_rejects_variables_without_sid() -> None:
    with pytest.raises(ValueError, match="content_variables requires content_sid"):
        send_whatsapp_message(
            "+5511999999999",
            content_variables={"1": "Maria"},
        )


@pytest.mark.parametrize(
    "name",
    [
        "Eliezer Ramos Silveira Junior",
        "José da Silva",
    ],
)
def test_encode_content_variables_compound_names(name: str) -> None:
    variables = {"1": name}
    encoded = encode_content_variables(variables)

    assert json.loads(encoded) == variables
    assert encoded == json.dumps(variables)


def test_encode_content_variables_accepts_pre_serialized_json_string() -> None:
    variables = {"1": "Eliezer Ramos Silveira Junior"}
    pre_serialized = json.dumps(variables)

    encoded = encode_content_variables(pre_serialized)

    assert encoded == pre_serialized
    assert json.loads(encoded) == variables


def test_encode_content_variables_recovers_from_double_serialization() -> None:
    variables = {"1": "Eliezer Ramos Silveira Junior"}
    double = json.dumps(json.dumps(variables))

    encoded = encode_content_variables(double)

    assert encoded == json.dumps(variables)
    assert json.loads(encoded) == variables


def test_send_whatsapp_message_template_rejects_double_serialized_variables(
    twilio_mocks,
) -> None:
    variables = {"1": "Eliezer Ramos Silveira Junior"}
    double = json.dumps(json.dumps(variables))

    send_whatsapp_message(
        "+5511999999999",
        content_sid="HX564c9577120a14f2d7d5517c2e26982b",
        content_variables=double,
    )

    kwargs = twilio_mocks.call_args.kwargs
    assert kwargs["content_variables"] == json.dumps(variables)
    assert json.loads(kwargs["content_variables"]) == variables
