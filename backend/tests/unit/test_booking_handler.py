"""Testes unitários — booking_handler e booking_state."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.memory import booking_state as bs
from agents.orchestrator.booking_handler import (
    booking_search_range,
    process_booking_turn,
)
from agents.workers.booking_agent import BookingConfirmationResult, SlotChoiceResult

pytestmark = pytest.mark.unit


def _slot(index: int, hour: int) -> dict:
    tz = datetime(2026, 6, 17, hour, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 17, hour, 30, tzinfo=timezone.utc)
    return bs.serialize_slot(tz, end, f"Qua 17/06/2026 {hour:02d}:00", index)


def _base_state(**overrides) -> dict:
    state = {
        "message": "quero agendar",
        "channel": "whatsapp",
        "user_id": "+5511999999999",
        "intent": "schedule",
        "confidence": 0.9,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "owner_user_id": str(uuid4()),
        "lead_id": str(uuid4()),
        "lead_name": "Maria",
    }
    state.update(overrides)
    return state


@pytest.fixture
def mock_redis():
    store: dict[str, str] = {}
    client = MagicMock()

    def setex(key, ttl, value):
        store[key] = value

    def get(key):
        return store.get(key)

    def delete(key):
        store.pop(key, None)

    client.setex = setex
    client.get = get
    client.delete = delete
    with patch.object(bs, "_get_redis", return_value=client):
        yield store


@pytest.mark.asyncio
async def test_voice_start_booking_offers_single_slot(mock_redis) -> None:
    slots = [_slot(1, 9), _slot(2, 10), _slot(3, 11)]
    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=slots),
    ):
        result = await process_booking_turn(_base_state(channel="voice"))

    assert result.get("booking_phase") == "awaiting_choice"
    ctx = result.get("booking_context") or ""
    assert "Modo VOZ" in ctx
    assert "Horários disponíveis:" not in ctx
    assert "09:00" in ctx or "Qua" in ctx
    saved = bs.get_booking_state("voice", "+5511999999999")
    assert saved is not None
    assert saved.get("voice_mode") is True
    assert len(saved.get("offered_slots") or []) == 1
    assert len(saved.get("all_slots") or []) == 3
    assert saved.get("slot_cursor") == 0


@pytest.mark.asyncio
async def test_voice_no_on_offer_advances_to_next_slot(mock_redis) -> None:
    all_slots = [_slot(1, 9), _slot(2, 10)]
    bs.set_booking_state(
        "voice",
        "+5511999999999",
        {
            "phase": "awaiting_choice",
            "voice_mode": True,
            "all_slots": all_slots,
            "slot_cursor": 0,
            "offered_slots": [all_slots[0]],
            "selected_slot": None,
        },
    )

    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="no", confidence=0.95)
        ),
    ), patch(
        "agents.orchestrator.booking_handler.create_appointment",
        new=AsyncMock(),
    ) as mock_create:
        result = await process_booking_turn(
            _base_state(channel="voice", message="não, outro horário", intent="other")
        )

    assert result.get("booking_phase") == "awaiting_choice"
    assert "10:00" in (result.get("booking_context") or "") or "Qua" in (
        result.get("booking_context") or ""
    )
    saved = bs.get_booking_state("voice", "+5511999999999")
    assert saved["slot_cursor"] == 1
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_yes_on_offer_creates_appointment(mock_redis) -> None:
    offered = [_slot(1, 14)]
    bs.set_booking_state(
        "voice",
        "+5511999999999",
        {
            "phase": "awaiting_choice",
            "voice_mode": True,
            "all_slots": offered,
            "slot_cursor": 0,
            "offered_slots": offered,
            "selected_slot": None,
        },
    )

    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="yes", confidence=0.95)
        ),
    ), patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=offered),
    ), patch(
        "agents.orchestrator.booking_handler.create_appointment",
        new=AsyncMock(
            return_value={"ok": True, "appointment": {"id": str(uuid4())}}
        ),
    ) as mock_create:
        result = await process_booking_turn(
            _base_state(channel="voice", message="sim, serve", intent="other")
        )

    assert result.get("booking_phase") == "done"
    assert "Modo VOZ" in (result.get("booking_context") or "")
    mock_create.assert_awaited_once()
    call_kwargs = mock_create.await_args.kwargs
    assert call_kwargs.get("channel") == "voice"
    assert bs.get_booking_state("voice", "+5511999999999") is None


@pytest.mark.asyncio
async def test_voice_no_more_slots_ends_booking(mock_redis) -> None:
    only = [_slot(1, 9)]
    bs.set_booking_state(
        "voice",
        "+5511999999999",
        {
            "phase": "awaiting_choice",
            "voice_mode": True,
            "all_slots": only,
            "slot_cursor": 0,
            "offered_slots": only,
            "selected_slot": None,
        },
    )

    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="no", confidence=0.95)
        ),
    ):
        result = await process_booking_turn(
            _base_state(channel="voice", message="não", intent="other")
        )

    assert result.get("booking_phase") == "done"
    assert "mais horários" in (result.get("booking_context") or "").lower()
    assert bs.get_booking_state("voice", "+5511999999999") is None


@pytest.mark.asyncio
async def test_voice_without_lead_id_degrades(mock_redis) -> None:
    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=[_slot(1, 9)]),
    ):
        result = await process_booking_turn(
            _base_state(channel="voice", lead_id=None)
        )

    assert "lead não identificado" in (result.get("booking_context") or "").lower()
    assert bs.get_booking_state("voice", "+5511999999999") is None


@pytest.mark.asyncio
async def test_voice_unclear_repeats_current_slot(mock_redis) -> None:
    offered = [_slot(1, 9)]
    bs.set_booking_state(
        "voice",
        "+5511999999999",
        {
            "phase": "awaiting_choice",
            "voice_mode": True,
            "all_slots": offered,
            "slot_cursor": 0,
            "offered_slots": offered,
            "selected_slot": None,
        },
    )

    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="unclear", confidence=0.2)
        ),
    ), patch(
        "agents.orchestrator.booking_handler.create_appointment",
        new=AsyncMock(),
    ) as mock_create:
        result = await process_booking_turn(
            _base_state(channel="voice", message="hmm", intent="other")
        )

    assert result.get("booking_phase") == "awaiting_choice"
    assert "não ficou clara" in (result.get("booking_context") or "").lower()
    mock_create.assert_not_awaited()
    saved = bs.get_booking_state("voice", "+5511999999999")
    assert saved["slot_cursor"] == 0


@pytest.mark.asyncio
async def test_start_booking_offers_slots(mock_redis) -> None:
    slots = [_slot(1, 9), _slot(2, 10)]
    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=slots),
    ):
        result = await process_booking_turn(_base_state())

    assert result.get("booking_phase") == "awaiting_choice"
    assert "Horários disponíveis" in (result.get("booking_context") or "")
    key = bs.booking_state_key("whatsapp", "+5511999999999")
    assert key.replace("booking:whatsapp:", "")  # key exists in mock via get
    saved = bs.get_booking_state("whatsapp", "+5511999999999")
    assert saved is not None
    assert saved["phase"] == "awaiting_choice"
    assert len(saved["offered_slots"]) == 2


@pytest.mark.asyncio
async def test_no_slots_degrades_gracefully(mock_redis) -> None:
    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=[]),
    ):
        result = await process_booking_turn(_base_state())

    assert "Não há horários livres" in (result.get("booking_context") or "")
    assert bs.get_booking_state("whatsapp", "+5511999999999") is None


@pytest.mark.asyncio
async def test_unclear_choice_does_not_confirm(mock_redis) -> None:
    offered = [_slot(1, 14), _slot(2, 15)]
    bs.set_booking_state(
        "whatsapp",
        "+5511999999999",
        {"phase": "awaiting_choice", "offered_slots": offered, "selected_slot": None},
    )

    with patch(
        "agents.orchestrator.booking_handler.extract_slot_choice",
        new=AsyncMock(
            return_value=SlotChoiceResult(choice="unclear", selected_index=None, confidence=0.3)
        ),
    ), patch(
        "agents.orchestrator.booking_handler.create_appointment",
        new=AsyncMock(),
    ) as mock_create:
        result = await process_booking_turn(
            _base_state(message="talvez", intent="other")
        )

    assert "esclarecimento" in (result.get("booking_context") or "").lower()
    mock_create.assert_not_awaited()
    saved = bs.get_booking_state("whatsapp", "+5511999999999")
    assert saved["phase"] == "awaiting_choice"


@pytest.mark.asyncio
async def test_happy_path_creates_appointment_and_clears_redis(mock_redis) -> None:
    offered = [_slot(1, 14)]
    selected = offered[0]
    parsed = bs.parse_slot(selected)

    bs.set_booking_state(
        "whatsapp",
        "+5511999999999",
        {
            "phase": "confirming",
            "offered_slots": offered,
            "selected_slot": selected,
        },
    )

    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="yes", confidence=0.95)
        ),
    ), patch(
        "agents.orchestrator.booking_handler.create_appointment",
        new=AsyncMock(
            return_value={"ok": True, "appointment": {"id": str(uuid4())}}
        ),
    ) as mock_create:
        result = await process_booking_turn(
            _base_state(message="sim, confirmo", intent="other")
        )

    assert result.get("booking_phase") == "done"
    assert "registrado com sucesso" in (result.get("booking_context") or "")
    mock_create.assert_awaited_once()
    assert bs.get_booking_state("whatsapp", "+5511999999999") is None


@pytest.mark.asyncio
async def test_conflict_on_create_reoffers_slots(mock_redis) -> None:
    offered = [_slot(1, 14), _slot(2, 15)]
    bs.set_booking_state(
        "whatsapp",
        "+5511999999999",
        {
            "phase": "confirming",
            "offered_slots": offered,
            "selected_slot": offered[0],
        },
    )

    fresh = [_slot(1, 16)]
    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="yes", confidence=0.95)
        ),
    ), patch(
        "agents.orchestrator.booking_handler.create_appointment",
        new=AsyncMock(return_value={"ok": False, "error": "slot_conflict"}),
    ), patch(
        "agents.orchestrator.booking_handler._fetch_offered_slots",
        new=AsyncMock(return_value=fresh),
    ):
        result = await process_booking_turn(_base_state(message="sim", intent="other"))

    assert "ocupado" in (result.get("booking_context") or "").lower()
    saved = bs.get_booking_state("whatsapp", "+5511999999999")
    assert saved["phase"] == "awaiting_choice"


def test_booking_search_range_covers_weekdays() -> None:
    start, end = booking_search_range(5)
    assert start.tzinfo is not None
    assert end > start


def test_booking_state_key_format() -> None:
    assert bs.booking_state_key("WhatsApp", "+5511") == "booking:whatsapp:+5511"
