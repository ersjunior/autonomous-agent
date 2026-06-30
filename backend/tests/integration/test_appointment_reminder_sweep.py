"""Integração — sweep de lembrete proativo de agendamentos (voice/telegram/whatsapp)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.models.agent import AgentMode
from app.models.appointment import AppointmentSource, AppointmentStatus
from app.models.lead_interaction import LeadInteraction
from app.services.appointment_service import create_appointment, format_slot_label
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

_REMINDER_SID = "HXappointmentreminder00000000000001"
_DUE_SID = "HXappointmentdue000000000000000001"

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
async def whatsapp_ctx(db_session) -> OwnerContext:
    ctx = await create_owner_context(db_session, email_suffix="appt-wa")
    ctx.lead.nome_cliente = "Maria Silva"
    await add_lead_base_channel(db_session, ctx.lead_base.id, "whatsapp")
    await db_session.flush()
    return ctx


def _enable_whatsapp_templates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_use_templates", True)
    monkeypatch.setattr(settings, "whatsapp_template_mode", "production")
    monkeypatch.setattr(settings, "twilio_phone_number", "+551150399542")
    monkeypatch.setattr(
        settings, "whatsapp_template_appointment_reminder", _REMINDER_SID
    )
    monkeypatch.setattr(settings, "whatsapp_template_appointment_due", _DUE_SID)


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
async def test_null_channel_counted_as_skipped_no_channel(
    mock_dt,
    mock_send,
    voice_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts_rem = _NOW + timedelta(minutes=20)

    null_ctx = await create_owner_context(db_session, email_suffix="appt-null")
    await add_lead_base_channel(db_session, null_ctx.lead_base.id, "voice")
    await _make_appointment(
        db_session, null_ctx, starts_at=starts_rem, channel=None
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["reminders_sent"] == 0
    assert stats["due_notified"] == 0
    assert stats["skipped_no_channel"] == 1
    mock_send.delay.assert_not_called()


@pytest.mark.asyncio
@patch(_REMINDER_PATCH)
@patch("worker.tasks.appointment_reminder_sweep.datetime")
async def test_whatsapp_channel_dispatches_in_sweep(
    mock_dt,
    mock_send,
    whatsapp_ctx: OwnerContext,
    db_session,
):
    mock_dt.now.return_value = _NOW
    mock_send.delay = MagicMock()
    starts = _NOW - timedelta(minutes=2)

    appt = await _make_appointment(
        db_session, whatsapp_ctx, starts_at=starts, channel="whatsapp"
    )

    stats = await _sweep_appointment_reminders_with_session(db_session)

    assert stats["due_notified"] == 1
    assert stats["skipped_no_channel"] == 0
    mock_send.delay.assert_called_once_with(str(appt.id), "due")


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
@patch(
    "app.services.outbound_delivery.build_outbound_twiml_url",
    return_value="https://test.example.com/outbound-say",
)
@patch(
    "app.services.outbound_delivery.build_outbound_audio_twiml_url",
    return_value="https://test.example.com/outbound-audio?audio=reminder.mp3",
)
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
    _mock_audio_twiml_url,
    _mock_say_twiml_url,
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


@pytest.mark.asyncio
@patch("app.services.outbound_delivery.send_whatsapp_message")
async def test_whatsapp_reminder_inside_24h_uses_freeform(
    mock_send_wa,
    whatsapp_ctx: OwnerContext,
    db_session,
    monkeypatch,
):
    """Dentro da janela 24h → texto livre (body), mesmo com templates ligados."""
    _enable_whatsapp_templates(monkeypatch)
    mock_send_wa.return_value = "SMfreeform123"
    starts = _NOW - timedelta(minutes=2)

    db_session.add(
        LeadInteraction(
            lead_id=whatsapp_ctx.lead.id,
            campaign_id=whatsapp_ctx.campaign.id,
            channel_type="whatsapp",
            status="em_andamento",
            data_ultimo_contato=_NOW - timedelta(hours=1),
        )
    )
    await db_session.flush()

    appt = await _make_appointment(
        db_session, whatsapp_ctx, starts_at=starts, channel="whatsapp"
    )

    result = await _send_appointment_reminder_with_session(
        db_session, str(appt.id), "due", commit=False
    )

    assert result["ok"] is True
    assert result["whatsapp_mode"] == "freeform"
    mock_send_wa.assert_called_once()
    args, kwargs = mock_send_wa.call_args
    assert kwargs.get("content_sid") is None
    body = kwargs.get("body") or (args[1] if len(args) > 1 else None)
    assert body
    assert "Chegou o horario" in body


@pytest.mark.asyncio
@patch("app.services.outbound_delivery.send_whatsapp_message")
async def test_whatsapp_reminder_outside_24h_uses_template(
    mock_send_wa,
    whatsapp_ctx: OwnerContext,
    db_session,
    monkeypatch,
):
    """Fora da janela 24h + SID configurado → template com nome e data/hora."""
    _enable_whatsapp_templates(monkeypatch)
    mock_send_wa.return_value = "SMtemplate123"
    starts = _NOW - timedelta(minutes=2)

    appt = await _make_appointment(
        db_session, whatsapp_ctx, starts_at=starts, channel="whatsapp"
    )

    result = await _send_appointment_reminder_with_session(
        db_session, str(appt.id), "due", commit=False
    )

    assert result["ok"] is True
    assert result["whatsapp_mode"] == "template"
    assert result["content_sid"] == _DUE_SID
    mock_send_wa.assert_called_once()
    kwargs = mock_send_wa.call_args.kwargs
    assert kwargs["content_sid"] == _DUE_SID
    assert kwargs["content_variables"] == {
        "1": "Maria Silva",
        "2": format_slot_label(starts),
    }
    assert kwargs.get("body") is None


@pytest.mark.asyncio
@patch("app.services.outbound_delivery.send_whatsapp_message")
async def test_whatsapp_reminder_outside_24h_empty_sid_fallback_freeform(
    mock_send_wa,
    whatsapp_ctx: OwnerContext,
    db_session,
    monkeypatch,
):
    """SID vazio → fallback freeform sem quebrar."""
    monkeypatch.setattr(settings, "whatsapp_use_templates", True)
    monkeypatch.setattr(settings, "whatsapp_template_mode", "production")
    monkeypatch.setattr(settings, "twilio_phone_number", "+551150399542")
    monkeypatch.setattr(settings, "whatsapp_template_appointment_due", "")
    mock_send_wa.return_value = "SMfallback123"
    starts = _NOW - timedelta(minutes=2)

    appt = await _make_appointment(
        db_session, whatsapp_ctx, starts_at=starts, channel="whatsapp"
    )

    result = await _send_appointment_reminder_with_session(
        db_session, str(appt.id), "due", commit=False
    )

    assert result["ok"] is True
    assert result["whatsapp_mode"] == "freeform"
    mock_send_wa.assert_called_once()
    kwargs = mock_send_wa.call_args.kwargs
    assert kwargs.get("content_sid") is None
    body = kwargs.get("body") or mock_send_wa.call_args.args[1]
    assert body


@pytest.mark.asyncio
@patch("app.services.outbound_delivery.send_whatsapp_message")
async def test_whatsapp_reminder_vs_due_use_distinct_template_sids(
    mock_send_wa,
    whatsapp_ctx: OwnerContext,
    db_session,
    monkeypatch,
):
    """kind reminder → appointment_reminder SID; kind due → appointment_due SID."""
    _enable_whatsapp_templates(monkeypatch)
    mock_send_wa.return_value = "SMtpl"
    starts_rem = _NOW + timedelta(hours=2)
    starts_due = _NOW - timedelta(minutes=2)

    appt_rem = await _make_appointment(
        db_session,
        whatsapp_ctx,
        starts_at=starts_rem,
        channel="whatsapp",
    )
    appt_due = await _make_appointment(
        db_session,
        whatsapp_ctx,
        starts_at=starts_due,
        channel="whatsapp",
    )

    await _send_appointment_reminder_with_session(
        db_session, str(appt_rem.id), "reminder", commit=False
    )
    rem_sid = mock_send_wa.call_args.kwargs["content_sid"]

    mock_send_wa.reset_mock()
    await _send_appointment_reminder_with_session(
        db_session, str(appt_due.id), "due", commit=False
    )
    due_sid = mock_send_wa.call_args.kwargs["content_sid"]

    assert rem_sid == _REMINDER_SID
    assert due_sid == _DUE_SID
    assert rem_sid != due_sid
