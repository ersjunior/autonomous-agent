"""Testes unitários — calendar_tool façade (degradação graciosa)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agents.tools.calendar_tool import (
    _parse_optional_uuid_safe,
    create_appointment,
    list_available_slots,
)
from app.services.appointment_service import AppointmentSlotConflictError

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_list_available_slots_returns_empty_on_failure() -> None:
    with patch(
        "agents.tools.calendar_tool.svc_list_available_slots",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        result = await list_available_slots(
            uuid4(),
            datetime(2026, 6, 17, tzinfo=timezone.utc),
            datetime(2026, 6, 18, tzinfo=timezone.utc),
        )
    assert result == []


def test_parse_optional_uuid_safe_invalid_returns_none() -> None:
    assert _parse_optional_uuid_safe("not-a-uuid") is None
    assert _parse_optional_uuid_safe("") is None
    assert _parse_optional_uuid_safe(None) is None


def test_parse_optional_uuid_safe_valid_string() -> None:
    uid = uuid4()
    assert _parse_optional_uuid_safe(str(uid)) == uid


@pytest.mark.asyncio
async def test_list_available_slots_propagates_agent_id() -> None:
    mock_svc = AsyncMock(return_value=[])
    uid = uuid4()
    aid = uuid4()
    with patch(
        "agents.tools.calendar_tool.svc_list_available_slots",
        new=mock_svc,
    ):
        await list_available_slots(
            uid,
            datetime(2026, 6, 17, tzinfo=timezone.utc),
            datetime(2026, 6, 18, tzinfo=timezone.utc),
            agent_id=str(aid),
        )
    mock_svc.assert_awaited_once()
    assert mock_svc.await_args.kwargs["agent_id"] == aid


@pytest.mark.asyncio
async def test_create_appointment_returns_structured_conflict() -> None:
    with patch(
        "agents.tools.calendar_tool.svc_create_appointment",
        new=AsyncMock(
            side_effect=AppointmentSlotConflictError("Slot overlaps an existing appointment")
        ),
    ):
        result = await create_appointment(
            uuid4(),
            uuid4(),
            datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 17, 12, 30, tzinfo=timezone.utc),
            title="Demo",
        )
    assert result["ok"] is False
    assert result["error"] == "slot_conflict"
