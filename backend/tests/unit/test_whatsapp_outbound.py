"""Unit tests — decisão de envio WhatsApp (janela 24h + templates W3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.whatsapp_outbound import (
    build_content_variables,
    is_within_whatsapp_service_window,
    resolve_whatsapp_send_mode,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


def _record(*, last_inbound: datetime | None) -> MagicMock:
    rec = MagicMock()
    rec.data_ultimo_contato = last_inbound
    return rec


@patch("app.services.whatsapp_outbound.datetime")
def test_is_within_window_true_when_inbound_within_24h(mock_dt) -> None:
    mock_dt.now.return_value = _NOW

    record = _record(last_inbound=_NOW - timedelta(hours=12))
    assert is_within_whatsapp_service_window(record) is True


@patch("app.services.whatsapp_outbound.datetime")
def test_is_within_window_false_when_inbound_older_than_24h(mock_dt) -> None:
    mock_dt.now.return_value = _NOW

    record = _record(last_inbound=_NOW - timedelta(hours=25))
    assert is_within_whatsapp_service_window(record) is False


def test_is_within_window_false_when_record_none() -> None:
    assert is_within_whatsapp_service_window(None) is False


def test_is_within_window_false_when_no_inbound() -> None:
    assert is_within_whatsapp_service_window(_record(last_inbound=None)) is False


def test_build_content_variables_uses_nome_cliente() -> None:
    lead = MagicMock()
    lead.nome_cliente = "  Maria  "
    assert build_content_variables(lead) == {"1": "Maria"}


def test_build_content_variables_fallback_cliente() -> None:
    lead = MagicMock()
    lead.nome_cliente = ""
    assert build_content_variables(lead) == {"1": "Cliente"}


@pytest.mark.parametrize(
    "name",
    [
        "Eliezer Ramos Silveira Junior",
        "José da Silva",
    ],
)
def test_build_content_variables_preserves_compound_names(name: str) -> None:
    lead = MagicMock()
    lead.nome_cliente = name
    assert build_content_variables(lead) == {"1": name}


def test_whatsapp_templates_enabled_combinations() -> None:
    from app.core.config import Settings

    s = Settings()
    s.whatsapp_use_templates = False
    s.whatsapp_template_mode = "production"
    assert s.whatsapp_templates_enabled() is False

    s.whatsapp_use_templates = True
    s.whatsapp_template_mode = "sandbox"
    assert s.whatsapp_templates_enabled() is False

    s.whatsapp_template_mode = "production"
    assert s.whatsapp_templates_enabled() is True

    s.whatsapp_template_mode = "auto"
    s.twilio_phone_number = "+14155238886"
    assert s.whatsapp_templates_enabled() is False

    s.twilio_phone_number = "+551150399542"
    assert s.whatsapp_templates_enabled() is True


@patch("app.services.whatsapp_outbound.settings")
def test_resolve_send_mode_templates_off_returns_freeform(settings_mock) -> None:
    settings_mock.whatsapp_templates_enabled.return_value = False

    mode = resolve_whatsapp_send_mode("inicial", None)

    assert mode.mode == "freeform"
    assert mode.content_sid is None


@patch("app.services.whatsapp_outbound.settings")
@patch("app.services.whatsapp_outbound.is_within_whatsapp_service_window", return_value=True)
def test_resolve_send_mode_inside_window_returns_freeform(
    _within,
    settings_mock,
) -> None:
    settings_mock.whatsapp_templates_enabled.return_value = True

    mode = resolve_whatsapp_send_mode("inicial", _record(last_inbound=_NOW))

    assert mode.mode == "freeform"


@patch("app.services.whatsapp_outbound.settings")
@patch("app.services.whatsapp_outbound.is_within_whatsapp_service_window", return_value=True)
def test_resolve_send_mode_ignore_window_forces_template(
    _within,
    settings_mock,
) -> None:
    settings_mock.whatsapp_templates_enabled.return_value = True
    settings_mock.resolved_whatsapp_template.return_value = (
        "HX564c9577120a14f2d7d5517c2e26982b"
    )
    lead = MagicMock()
    lead.nome_cliente = "Eliezer Ramos Silveira Junior"

    mode = resolve_whatsapp_send_mode(
        "inicial",
        _record(last_inbound=_NOW),
        lead=lead,
        ignore_service_window=True,
    )

    assert mode.mode == "template"
    assert mode.content_variables == {"1": "Eliezer Ramos Silveira Junior"}
    _within.assert_not_called()


@patch("app.services.whatsapp_outbound.settings")
@patch("app.services.whatsapp_outbound.is_within_whatsapp_service_window", return_value=False)
def test_resolve_send_mode_cold_lead_returns_template(
    _within,
    settings_mock,
) -> None:
    settings_mock.whatsapp_templates_enabled.return_value = True
    settings_mock.resolved_whatsapp_template.return_value = (
        "HX564c9577120a14f2d7d5517c2e26982b"
    )
    lead = MagicMock()
    lead.nome_cliente = "João"

    mode = resolve_whatsapp_send_mode("inicial", None, lead=lead)

    assert mode.mode == "template"
    assert mode.content_sid == "HX564c9577120a14f2d7d5517c2e26982b"
    assert mode.content_variables == {"1": "João"}
    settings_mock.resolved_whatsapp_template.assert_called_once_with("inicial")


def test_resolved_whatsapp_template_followup_sid() -> None:
    from app.core.config import Settings

    s = Settings()
    assert s.resolved_whatsapp_template("followup") == (
        "HX6afa2ef98be8d7f1e67ef203bb751c95"
    )
