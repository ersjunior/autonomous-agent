"""Testes unitários — booking_handler e booking_state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agents.memory import booking_state as bs
from agents.orchestrator.booking_handler import (
    _agent_id_for_slots,
    _fetch_offered_slots,
    booking_search_range,
    process_booking_turn,
    voice_offer_phrase,
)
from agents.workers.booking_agent import BookingConfirmationResult, SlotChoiceResult
from app.core.config import APPOINTMENT_TIMEZONE

pytestmark = pytest.mark.unit

TZ = ZoneInfo(APPOINTMENT_TIMEZONE)


def _slot(index: int, hour: int, minute: int = 0) -> dict:
    start_local = datetime(2026, 6, 17, hour, minute, tzinfo=TZ)
    end_local = start_local + timedelta(minutes=30)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    label = f"Qua 17/06/2026 {hour:02d}:{minute:02d}"
    return bs.serialize_slot(start_utc, end_utc, label, index)


def _voice_text(result: dict) -> str:
    return (result.get("response") or "").strip()


def _assert_spoken_voice_phrase(text: str) -> None:
    assert text
    assert ":" not in text
    assert "/" not in text


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
    phrase = _voice_text(result)
    _assert_spoken_voice_phrase(phrase)
    assert "serve" in phrase.lower()
    assert "horas" in phrase.lower()
    assert result.get("booking_context") is None
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
    phrase = _voice_text(result)
    _assert_spoken_voice_phrase(phrase)
    assert "dez horas" in phrase
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
    phrase = _voice_text(result)
    _assert_spoken_voice_phrase(phrase)
    assert "agendado" in phrase.lower()
    assert "mais alguma coisa" in phrase.lower()
    mock_create.assert_awaited_once()
    call_kwargs = mock_create.await_args.kwargs
    assert call_kwargs.get("channel") == "voice"
    assert bs.get_booking_state("voice", "+5511999999999") is None


@pytest.mark.asyncio
async def test_voice_restart_booking_after_done(mock_redis) -> None:
    """Após done (Redis limpo), intent=schedule reinicia oferta na mesma ligação."""
    offered = [_slot(1, 14), _slot(2, 15)]
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
    ):
        done_result = await process_booking_turn(
            _base_state(
                channel="voice",
                message="sim, serve",
                intent="other",
                twilio_call_sid="CA-restart",
            )
        )

    assert done_result.get("booking_phase") == "done"
    assert bs.get_booking_state("voice", "+5511999999999") is None

    next_slots = [_slot(1, 10), _slot(2, 11)]
    with (
        patch(
            "agents.orchestrator.booking_handler.list_available_slots",
            new=AsyncMock(return_value=next_slots),
        ),
        patch("app.services.voice_call_state.clear_wrap_up_pending") as clear_wrap,
    ):
        restart = await process_booking_turn(
            _base_state(
                channel="voice",
                message="tem outro horario",
                intent="schedule",
                twilio_call_sid="CA-restart",
                conversation_history=[
                    {"role": "user", "content": "sim"},
                    {
                        "role": "assistant",
                        "content": _voice_text(done_result),
                    },
                ],
            )
        )

    clear_wrap.assert_called_once_with("CA-restart")

    assert restart.get("booking_phase") == "awaiting_choice"
    phrase = _voice_text(restart)
    _assert_spoken_voice_phrase(phrase)
    assert "serve" in phrase.lower()
    saved = bs.get_booking_state("voice", "+5511999999999")
    assert saved is not None
    assert saved["phase"] == "awaiting_choice"
    assert saved.get("voice_mode") is True


@pytest.mark.asyncio
async def test_voice_zombie_redis_phase_restarts_on_schedule(mock_redis) -> None:
    """Estado Redis inativo (fase zumbi) + schedule limpa e reinicia."""
    bs.set_booking_state(
        "voice",
        "+5511999999999",
        {"phase": "done", "voice_mode": True},
    )
    slots = [_slot(1, 9)]

    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=slots),
    ):
        result = await process_booking_turn(
            _base_state(channel="voice", message="tem outro horario", intent="schedule")
        )

    assert result.get("booking_phase") == "awaiting_choice"
    saved = bs.get_booking_state("voice", "+5511999999999")
    assert saved is not None
    assert saved["phase"] == "awaiting_choice"


@pytest.mark.asyncio
async def test_voice_booking_no_advances_slot_not_hangup(mock_redis) -> None:
    """Regressão: 'não' na oferta avança slot — não encerra a ligação."""
    offered = [_slot(1, 9), _slot(2, 10)]
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
            return_value=BookingConfirmationResult(decision="no", confidence=0.95)
        ),
    ):
        result = await process_booking_turn(
            _base_state(channel="voice", message="não", intent="question")
        )

    assert result.get("booking_phase") == "awaiting_choice"
    assert result.get("should_hangup") is not True
    assert _voice_text(result)


@pytest.mark.asyncio
async def test_voice_success_sets_wrap_up_pending(mock_redis) -> None:
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
    ), patch(
        "app.services.voice_call_state.set_wrap_up_pending",
    ) as set_wrap:
        await process_booking_turn(
            _base_state(
                channel="voice",
                message="sim",
                intent="other",
                twilio_call_sid="CA-wrap-up",
            )
        )

    set_wrap.assert_called_once_with("CA-wrap-up", from_number="+5511999999999")


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
    phrase = _voice_text(result)
    assert "mais horários" in phrase.lower()
    _assert_spoken_voice_phrase(phrase)
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

    phrase = _voice_text(result)
    assert "agendar" in phrase.lower() or "consegui" in phrase.lower()
    _assert_spoken_voice_phrase(phrase)
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
    phrase = _voice_text(result)
    _assert_spoken_voice_phrase(phrase)
    assert "serve" in phrase.lower()
    mock_create.assert_not_awaited()
    saved = bs.get_booking_state("voice", "+5511999999999")
    assert saved["slot_cursor"] == 0


def test_voice_offer_phrase_uses_spoken_label() -> None:
    slot = _slot(1, 14, 30)
    phrase = voice_offer_phrase(bs.parse_slot(slot))
    _assert_spoken_voice_phrase(phrase)
    assert "quatorze e trinta" in phrase
    assert len(phrase) <= 70


@pytest.mark.asyncio
async def test_start_booking_offers_slots(mock_redis) -> None:
    slots = [_slot(1, 9), _slot(2, 10)]
    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=slots),
    ):
        result = await process_booking_turn(_base_state())

    assert result.get("booking_phase") == "awaiting_choice"
    ctx = result.get("booking_context") or ""
    assert "Horários disponíveis" in ctx
    assert "09:00" in ctx or "17/06" in ctx
    assert result.get("response") is None
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


def test_agent_id_for_slots_from_state() -> None:
    aid = str(uuid4())
    state = _base_state(agent_id=aid)
    assert _agent_id_for_slots(state) == aid


def test_agent_id_for_slots_missing_returns_none() -> None:
    state = _base_state()
    state.pop("agent_id", None)
    assert _agent_id_for_slots(state) is None


@pytest.mark.asyncio
async def test_fetch_offered_slots_passes_agent_id_to_calendar() -> None:
    aid = str(uuid4())
    owner = str(uuid4())
    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=[]),
    ) as mock_list:
        await _fetch_offered_slots(owner, aid)
    mock_list.assert_awaited_once()
    assert mock_list.await_args.kwargs["agent_id"] == aid

