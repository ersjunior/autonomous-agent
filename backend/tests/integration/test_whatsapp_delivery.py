"""Integração — gravação de MessageSid e status de entrega no outbound WhatsApp."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.integration.helpers import OwnerContext
from worker.tasks.lead_tracking import upsert_lead_interaction

pytestmark = pytest.mark.integration


async def test_upsert_stores_twilio_message_sid_and_delivery_status(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        status="acionado",
        twilio_message_sid="SMintegration123",
        last_delivery_status="queued",
    )

    assert record.twilio_message_sid == "SMintegration123"
    assert record.last_delivery_status == "queued"
    assert record.last_delivery_error_code is None


@patch(
    "worker.tasks.outbound_campaign.send_whatsapp_message",
    return_value="SMoutbound456",
)
async def test_deliver_message_whatsapp_returns_message_sid(
    _mock_send,
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    from worker.tasks.outbound_campaign import _deliver_message

    result = await _deliver_message(
        db_session,
        owner_ctx.lead,
        owner_ctx.campaign,
        "whatsapp",
        owner_ctx.lead.telefone_1 or "+5511999999999",
        "Olá teste",
    )

    assert result.ok is True
    assert result.twilio_message_sid == "SMoutbound456"
    assert result.initial_delivery_status == "queued"
