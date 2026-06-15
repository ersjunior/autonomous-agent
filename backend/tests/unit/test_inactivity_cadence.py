"""Unit tests — helpers de silêncio do cliente (cadência / inactivity sweep)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.lead_interaction import LeadInteraction
from app.services.activation_cadence import (
    client_is_silent,
    client_silent_since_warning,
    lead_has_responded,
)

_NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
_EARLIER = datetime(2026, 6, 14, 11, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 6, 14, 13, 0, tzinfo=timezone.utc)


def _li(**kwargs) -> LeadInteraction:
    defaults = {
        "lead_id": uuid.uuid4(),
        "campaign_id": uuid.uuid4(),
        "channel_type": "whatsapp",
    }
    defaults.update(kwargs)
    return LeadInteraction(**defaults)


def test_lead_has_responded_when_inbound_after_outbound() -> None:
    record = _li(
        data_ultima_tentativa=_EARLIER,
        data_ultimo_contato=_LATER,
    )
    assert lead_has_responded(record) is True
    assert client_is_silent(record) is False


def test_client_is_silent_when_agent_spoke_last() -> None:
    record = _li(
        data_ultima_tentativa=_LATER,
        data_ultimo_contato=_EARLIER,
    )
    assert lead_has_responded(record) is False
    assert client_is_silent(record) is True


def test_client_silent_since_warning_no_inbound() -> None:
    record = _li(
        inactivity_warning_sent_at=_EARLIER,
        data_ultimo_contato=None,
    )
    assert client_silent_since_warning(record) is True


def test_client_not_silent_since_warning_when_replied_after() -> None:
    record = _li(
        inactivity_warning_sent_at=_EARLIER,
        data_ultimo_contato=_LATER,
    )
    assert client_silent_since_warning(record) is False
