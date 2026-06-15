"""Unit tests — status de entrega WhatsApp (Twilio callback)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.whatsapp_delivery import (
    apply_whatsapp_delivery_status,
    delivery_badge_label,
    should_apply_delivery_update,
)

pytestmark = pytest.mark.unit


def test_should_apply_delivery_update_progression() -> None:
    assert should_apply_delivery_update(None, "queued") is True
    assert should_apply_delivery_update("queued", "sent") is True
    assert should_apply_delivery_update("sent", "delivered") is True
    assert should_apply_delivery_update("delivered", "sent") is False
    assert should_apply_delivery_update("queued", "failed") is True
    assert should_apply_delivery_update("failed", "sent") is False


def test_delivery_badge_label_mapping() -> None:
    assert delivery_badge_label("delivered") == "Entregue"
    assert delivery_badge_label("read") == "Entregue"
    assert delivery_badge_label("queued") == "Enviado"
    assert delivery_badge_label("failed", "63015") == "Falhou (sem opt-in no sandbox)"
    assert delivery_badge_label("undelivered", "63016") == "Falhou (fora da janela de 24h)"


@pytest.mark.asyncio
async def test_apply_delivery_delivered_updates_li() -> None:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.lead_id = uuid.uuid4()
    record.last_delivery_status = "queued"
    record.last_delivery_error_code = None

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=record))
    )

    ok = await apply_whatsapp_delivery_status(
        session,
        message_sid="SMtest123",
        message_status="delivered",
    )

    assert ok is True
    assert record.last_delivery_status == "delivered"
    assert record.last_delivery_error_code is None
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_apply_delivery_failed_stores_error_code() -> None:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.lead_id = uuid.uuid4()
    record.last_delivery_status = "sent"
    record.last_delivery_error_code = None

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=record))
    )

    ok = await apply_whatsapp_delivery_status(
        session,
        message_sid="SMfail",
        message_status="undelivered",
        error_code="63015",
    )

    assert ok is True
    assert record.last_delivery_status == "undelivered"
    assert record.last_delivery_error_code == "63015"


@pytest.mark.asyncio
async def test_apply_delivery_idempotent_duplicate() -> None:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.lead_id = uuid.uuid4()
    record.last_delivery_status = "delivered"
    record.last_delivery_error_code = None

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=record))
    )

    ok = await apply_whatsapp_delivery_status(
        session,
        message_sid="SMdup",
        message_status="delivered",
    )

    assert ok is True
    assert record.last_delivery_status == "delivered"


@pytest.mark.asyncio
async def test_apply_delivery_li_not_found() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    ok = await apply_whatsapp_delivery_status(
        session,
        message_sid="SMmissing",
        message_status="delivered",
    )

    assert ok is False
    session.flush.assert_not_awaited()
