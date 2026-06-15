"""API tests — webhook de status de entrega WhatsApp."""

from __future__ import annotations

import uuid

import pytest

from app.models.lead_interaction import LeadInteraction

pytestmark = pytest.mark.api

STATUS_URL = "/api/v1/channels/webhooks/whatsapp/status"


async def test_whatsapp_status_callback_delivered_updates_li(
    client,
    db_session,
    owner_ctx,
) -> None:
    message_sid = f"SM{uuid.uuid4().hex[:24]}"

    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="acionado",
        twilio_message_sid=message_sid,
        last_delivery_status="queued",
    )
    db_session.add(li)
    await db_session.commit()

    response = await client.post(
        STATUS_URL,
        data={
            "MessageSid": message_sid,
            "MessageStatus": "delivered",
        },
    )

    assert response.status_code == 204
    await db_session.refresh(li)
    assert li.last_delivery_status == "delivered"
    assert li.last_delivery_error_code is None


async def test_whatsapp_status_callback_failed_stores_error_code(
    client,
    db_session,
    owner_ctx,
) -> None:
    message_sid = f"SM{uuid.uuid4().hex[:24]}"

    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="acionado",
        twilio_message_sid=message_sid,
        last_delivery_status="queued",
    )
    db_session.add(li)
    await db_session.commit()

    response = await client.post(
        STATUS_URL,
        data={
            "MessageSid": message_sid,
            "MessageStatus": "failed",
            "ErrorCode": "63015",
            "ErrorMessage": "Sandbox recipient not allowed",
        },
    )

    assert response.status_code == 204
    await db_session.refresh(li)
    assert li.last_delivery_status == "failed"
    assert li.last_delivery_error_code == "63015"


async def test_whatsapp_status_callback_unknown_sid_returns_204(
    client,
) -> None:
    response = await client.post(
        STATUS_URL,
        data={
            "MessageSid": "SMunknown",
            "MessageStatus": "delivered",
        },
    )

    assert response.status_code == 204


async def test_whatsapp_status_callback_idempotent_sequence(
    client,
    db_session,
    owner_ctx,
) -> None:
    message_sid = f"SM{uuid.uuid4().hex[:24]}"

    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="acionado",
        twilio_message_sid=message_sid,
        last_delivery_status="queued",
    )
    db_session.add(li)
    await db_session.commit()

    for status in ("sent", "delivered", "delivered"):
        response = await client.post(
            STATUS_URL,
            data={"MessageSid": message_sid, "MessageStatus": status},
        )
        assert response.status_code == 204

    await db_session.refresh(li)
    assert li.last_delivery_status == "delivered"
