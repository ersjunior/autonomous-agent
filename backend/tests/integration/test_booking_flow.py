"""Integração — fluxo conversacional de agendamento (E2E simulado, texto)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select

from agents.memory import booking_state as bs
from agents.orchestrator.graph import handle_booking
from agents.workers.booking_agent import BookingConfirmationResult, SlotChoiceResult
from app.models.appointment import Appointment, AppointmentStatus
from tests.integration.helpers import OwnerContext

pytestmark = pytest.mark.integration


def _make_slot(start_hour: int, index: int) -> dict:
    starts = datetime(2026, 6, 17, start_hour + 3, 0, tzinfo=timezone.utc)  # 09 BRT ≈ 12 UTC
    ends = datetime(2026, 6, 17, start_hour + 3, 30, tzinfo=timezone.utc)
    return bs.serialize_slot(starts, ends, f"Qua 17/06/2026 {start_hour:02d}:00", index)


@pytest.fixture
def clean_booking_redis(clean_redis):
    yield


def _state(owner: OwnerContext, message: str, intent: str = "schedule") -> dict:
    return {
        "message": message,
        "channel": "whatsapp",
        "user_id": "+5511999887766",
        "intent": intent,
        "confidence": 0.9,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
        "owner_user_id": str(owner.user.id),
        "lead_id": str(owner.lead.id),
        "lead_name": owner.lead.nome_cliente,
        "agent_id": str(owner.agent.id),
    }


async def test_booking_flow_end_to_end(
    owner_ctx: OwnerContext,
    db_session,
    clean_booking_redis,
) -> None:
    user_id = "+5511999887766"
    channel = "whatsapp"
    slot1 = _make_slot(9, 1)
    slot2 = _make_slot(10, 2)
    offered = [slot1, slot2]
    parsed = bs.parse_slot(slot1)

    with patch(
        "agents.orchestrator.booking_handler.list_available_slots",
        new=AsyncMock(return_value=[{"starts_at": parsed["starts_at"], "ends_at": parsed["ends_at"], "label": parsed["label"]}, {"starts_at": bs.parse_slot(slot2)["starts_at"], "ends_at": bs.parse_slot(slot2)["ends_at"], "label": slot2["label"]}]),
    ):
        r1 = await handle_booking(_state(owner_ctx, "Quero agendar uma reunião"))
    assert r1.get("booking_phase") == "awaiting_choice"
    saved = bs.get_booking_state(channel, user_id)
    assert saved is not None

    with patch(
        "agents.orchestrator.booking_handler.extract_slot_choice",
        new=AsyncMock(
            return_value=SlotChoiceResult(choice="clear", selected_index=1, confidence=0.9)
        ),
    ), patch(
        "agents.orchestrator.booking_handler._fetch_offered_slots",
        new=AsyncMock(return_value=offered),
    ):
        r2 = await handle_booking(_state(owner_ctx, "opção 1", intent="other"))
    assert r2.get("booking_phase") == "confirming"

    with patch(
        "agents.orchestrator.booking_handler.extract_booking_confirmation",
        new=AsyncMock(
            return_value=BookingConfirmationResult(decision="yes", confidence=0.95)
        ),
    ):
        async def _create_via_test_session(user_id, lead_id, starts_at, ends_at, **kwargs):
            from app.services.appointment_service import create_appointment as svc_create

            appt = await svc_create(
                db_session,
                owner_ctx.user.id,
                owner_ctx.lead.id,
                starts_at,
                ends_at,
                title=kwargs.get("title", "Agendamento via whatsapp"),
                agent_id=owner_ctx.agent.id,
                channel=kwargs.get("channel"),
            )
            return {"ok": True, "appointment": {"id": str(appt.id)}}

        with patch(
            "agents.orchestrator.booking_handler.create_appointment",
            new=AsyncMock(side_effect=_create_via_test_session),
        ):
            r3 = await handle_booking(_state(owner_ctx, "sim, confirmo", intent="other"))

    assert r3.get("booking_phase") == "done"
    assert bs.get_booking_state(channel, user_id) is None

    rows = await db_session.execute(
        select(Appointment).where(
            Appointment.user_id == owner_ctx.user.id,
            Appointment.lead_id == owner_ctx.lead.id,
        )
    )
    appts = list(rows.scalars().all())
    assert len(appts) == 1
    assert appts[0].status == AppointmentStatus.SCHEDULED.value
    assert appts[0].channel == "whatsapp"
