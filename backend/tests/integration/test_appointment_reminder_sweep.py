"""Integração — sweep de lembrete proativo de agendamentos (Fatia 1: voice/telegram)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent import AgentMode
from app.models.appointment import AppointmentSource, AppointmentStatus
from app.services.appointment_service import create_appointment
from tests.integration.helpers import (
    OwnerContext,
    add_lead_base_channel,
    create_owner_context,
)
from worker.tasks.appointment_reminder import _send_appointment_reminder_with_session
from worker.tasks.appointment_reminder_sweep import _sweep_appointment_reminders_with_session
from worker.tasks.outbound_campaign import _send_campaign_message

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc)

_REMINDER_PATCH = "worker.tasks.appointment_reminder_sweep.send_appointment_reminder"


def _ends(starts: datetime, minutes: int = 30) -> datetime:
    return starts + timedelta(minutes=minutes)


async def _make_appointment(
    db_session,
    owner_ctx: OwnerContext,
    *,
    starts_at: datetime,
    channel: str | None,
    status: str = AppointmentStatus.SCHEDULED.value,
) -> object:
    appt = await create_appointment(
        db_session,
        owner_ctx.user.id,
        owner_ctx.lead.id,
        starts_at,
        _ends(starts_at),
        title="Teste",
        channel=channel,
        agent_id=owner_ctx.agent.id,
        created_by=AppointmentSource.AGENT,
        status=status,
    )
    await db_session.flush()
    return appt


@pytest.fixture
async def voice_ctx(db_session) -> OwnerContext:
    ctx = await create_owner_context(db_session, email_suffix="appt-voice")
    await add_lead_base_channel(db_session, ctx.lead_base.id, "voice")
    return ctx


@pytest.fixture
async def telegram_ctx(db_session) -> OwnerContext:
    ctx = await create_owner_context(db_session, email_suffix="appt-tg")
    ctx.lead.aux_values = {"telegram_id": "99887766"}
    await add_lead_base_channel(db_session, ctx.lead_base.id, "telegram")
    await db_session.flush()
    return ctx


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_reminder_sends_in_window_and_marks_idempotent(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW + timedelta(minutes=20)

    appt = await _make_appointment(
        db_session, voice_ctx, starts_at=starts, channel="voice"
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["reminders_sent"] == 1
    assert stats["due_notified"] == 0
    mock_send.delay.assert_called_once_with(str(appt.id), "reminder")

    await db_session.refresh(appt)
    assert appt.reminder_sent_at == _NOW
    assert appt.due_notified_at is None

    mock_send.delay.reset_mock()
    stats2 = await _sweep_appointment_reminders_with_session(db_session)
    assert stats2["reminders_sent"] == 0
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_reminder_not_sent_when_less_than_grace_minutes(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW + timedelta(minutes=3)

    await _make_appointment(db_session, voice_ctx, starts_at=starts, channel="voice")

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["reminders_sent"] == 0
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_due_notified_in_window_and_idempotent(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=5)

    appt = await _make_appointment(
        db_session, voice_ctx, starts_at=starts, channel="voice"
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["due_notified"] == 1
    assert stats["reminders_sent"] == 0
    mock_send.delay.assert_called_once_with(str(appt.id), "due")

    await db_session.refresh(appt)
    assert appt.due_notified_at == _NOW

    mock_send.delay.reset_mock()
    stats2 = await _sweep_appointment_reminders_with_session(db_session)
    assert stats2["due_notified"] == 0
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_due_not_sent_when_too_late(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=20)

    await _make_appointment(db_session, voice_ctx, starts_at=starts, channel="voice")

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["due_notified"] == 0
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_whatsapp_and_null_channel_counted_as_skipped(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts_due = _NOW - timedelta(minutes=2)
    starts_rem = _NOW + timedelta(minutes=20)

    await _make_appointment(
        db_session, voice_ctx, starts_at=starts_due, channel="whatsapp"
    )

    null_ctx = await create_owner_context(db_session, email_suffix="appt-null")
    await add_lead_base_channel(db_session, null_ctx.lead_base.id, "voice")
    await _make_appointment(
        db_session, null_ctx, starts_at=starts_rem, channel=None
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["reminders_sent"] == 0
    assert stats["due_notified"] == 0
    assert stats["skipped_whatsapp"] == 2
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_cancelled_and_completed_not_dispatched(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=2)

    await _make_appointment(
        db_session,
        voice_ctx,
        starts_at=starts,
        channel="voice",
        status=AppointmentStatus.CANCELLED.value,
    )
    await _make_appointment(
        db_session,
        voice_ctx,
        starts_at=starts,
        channel="voice",
        status=AppointmentStatus.COMPLETED.value,
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)
    assert stats["due_notified"] == 0
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_telegram_channel_dispatches(
    mock_dt,
    mock_send,
    telegram_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=1)

    appt = await _make_appointment(
        db_session, telegram_ctx, starts_at=starts, channel="telegram"
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)
    assert stats["due_notified"] == 1
    mock_send.delay.assert_called_once_with(str(appt.id), "due")


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_sweep_dispatches_even_without_resolvable_campaign(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    """Campanha ausente não bloqueia o sweep — entrega direta do lembrete."""
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=1)

    appt = await _make_appointment(
        db_session, voice_ctx, starts_at=starts, channel="voice"
    )

    with patch(
        "worker.tasks.appointment_reminder.resolve_campaign_for_lead",
        new_callable=AsyncMock,
        return_value=None,
    ):
        stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["due_notified"] == 1
    mock_send.delay.assert_called_once_with(str(appt.id), "due")
    await db_session.refresh(appt)
    assert appt.due_notified_at == _NOW


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_receptive_agent_does_not_block_sweep(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    """Agente RECEPTIVE na campanha não impede enfileirar o lembrete."""
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=1)

    appt = await _make_appointment(
        db_session, voice_ctx, starts_at=starts, channel="voice"
    )
    voice_ctx.agent.mode = AgentMode.RECEPTIVE
    await db_session.flush()

    stats = await _sweep_appointment_reminders_with_session(db_session)
    assert stats["due_notified"] == 1
    mock_send.delay.assert_called_once_with(str(appt.id), "due")
    await db_session.refresh(appt)
    assert appt.due_notified_at == _NOW


@pytest.mark.asyncio
@patch("app.services.voice_call_state.remember_call_from_number")
@patch("app.services.outbound_delivery.make_outbound_call", return_value="CAtest123")
@patch(
    "app.services.outbound_delivery.gerar_audio_chamada",
    new_callable=AsyncMock,
    return_value="reminder.mp3",
)
async def test_appointment_reminder_task_delivers_voice_with_receptive_agent(
    _mock_audio,
    mock_call,
    _mock_remember,
    voice_ctx: OwnerContext,
    db_session,
):
    """Task de lembrete disca mesmo com Agente_Receptivo na campanha."""
    voice_ctx.agent.mode = AgentMode.RECEPTIVE
    await db_session.flush()
    starts = _NOW - timedelta(minutes=1)
    appt = await _make_appointment(
        db_session, voice_ctx, starts_at=starts, channel="voice"
    )

    result = await _send_appointment_reminder_with_session(
        db_session, str(appt.id), "due", commit=False
    )

    assert result["ok"] is True
    assert result["channel"] == "voice"
    assert result["lead_interaction_recorded"] is True
    mock_call.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.outbound_delivery.send_telegram_message", new_callable=AsyncMock)
@patch(
    "worker.tasks.appointment_reminder.resolve_campaign_for_lead",
    new_callable=AsyncMock,
    return_value=None,
)
async def test_appointment_reminder_task_without_campaign_still_delivers(
    _mock_campaign,
    mock_telegram,
    telegram_ctx: OwnerContext,
    db_session,
):
    starts = _NOW - timedelta(minutes=1)
    appt = await _make_appointment(
        db_session, telegram_ctx, starts_at=starts, channel="telegram"
    )

    result = await _send_appointment_reminder_with_session(
        db_session, str(appt.id), "due", commit=False
    )

    assert result["ok"] is True
    assert result["lead_interaction_recorded"] is False
    mock_telegram.assert_awaited_once()


@pytest.mark.asyncio
async def test_campaign_outbound_still_blocks_receptive_agent(
    voice_ctx: OwnerContext,
    db_session,
):
    """Prospecção via send_campaign_message continua bloqueada para RECEPTIVE."""

    class _SessionCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *_exc):
            return None

    voice_ctx.agent.mode = AgentMode.RECEPTIVE
    await db_session.flush()

    with (
        patch(
            "app.services.settings_sync.ensure_settings_fresh_async",
            new_callable=AsyncMock,
        ),
        patch(
            "worker.tasks.outbound_campaign.AsyncSessionLocal",
            lambda: _SessionCtx(db_session),
        ),
    ):
        result = await _send_campaign_message(
            str(voice_ctx.lead.id),
            str(voice_ctx.campaign.id),
            "voice",
        )

    assert result["blocked"] is True
    assert result["reason"] == "campaign_agent_not_active"
