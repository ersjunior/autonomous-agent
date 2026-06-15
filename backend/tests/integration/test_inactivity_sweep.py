"""Integração — sweep de inatividade em mensageria (lifecycle_version >= 1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.inactivity_text import INACTIVITY_WARNING_MESSAGE
from app.models.agent import AgentMode
from app.models.lead_interaction import LeadInteraction
from tests.integration.helpers import OwnerContext, create_lead_interaction, tabulacao_codigo_for
from worker.tasks.inactivity_sweep import _sweep_inactivity_with_session
from worker.tasks.lead_tracking import upsert_lead_interaction

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


async def _make_silent_li(
    db_session,
    owner_ctx: OwnerContext,
    **kwargs,
) -> LeadInteraction:
    agent_ts = kwargs.pop("agent_spoke_at", _NOW - timedelta(minutes=25))
    li = await create_lead_interaction(
        db_session,
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type=kwargs.pop("channel", "whatsapp"),
        status="em_andamento",
        lifecycle_version=kwargs.pop("lifecycle_version", 1),
        data_acionamento=agent_ts,
        data_ultima_tentativa=agent_ts,
        data_ultimo_contato=kwargs.pop("client_spoke_at", None),
        inactivity_warning_sent_at=kwargs.pop("warning_sent_at", None),
    )
    await db_session.flush()
    return li


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SM123")
@patch("worker.tasks.inactivity_sweep.datetime")
async def test_inactivity_sweep_sends_warning_stays_em_andamento(
    mock_dt,
    mock_send,
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
):
    mock_dt.now.return_value = _NOW
    li = await _make_silent_li(db_session, owner_ctx)

    with patch("worker.tasks.inactivity_sweep.settings") as mock_settings:
        mock_settings.inactivity_warning_minutes = 20
        mock_settings.inactivity_close_minutes = 20
        stats = await _sweep_inactivity_with_session(db_session)

    assert stats["warnings_sent"] == 1
    assert stats["closed"] == 0

    refreshed = await db_session.get(LeadInteraction, li.id)
    assert refreshed is not None
    assert refreshed.status == "em_andamento"
    assert refreshed.inactivity_warning_sent_at == _NOW
    mock_send.assert_called_once_with(
        owner_ctx.lead.telefone_1,
        INACTIVITY_WARNING_MESSAGE,
    )


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SM123")
@patch("worker.tasks.inactivity_sweep.datetime")
async def test_inactivity_sweep_closes_active_as_abandono(
    mock_dt,
    _mock_send,
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
):
    mock_dt.now.return_value = _NOW
    warning_at = _NOW - timedelta(minutes=25)
    li = await _make_silent_li(
        db_session,
        owner_ctx,
        warning_sent_at=warning_at,
        agent_spoke_at=warning_at,
    )

    with patch("worker.tasks.inactivity_sweep.settings") as mock_settings:
        mock_settings.inactivity_warning_minutes = 20
        mock_settings.inactivity_close_minutes = 20
        stats = await _sweep_inactivity_with_session(db_session)

    assert stats["warnings_sent"] == 0
    assert stats["closed"] == 1

    refreshed = await db_session.get(LeadInteraction, li.id)
    assert refreshed is not None
    assert refreshed.status == "nao_atendido"
    assert await tabulacao_codigo_for(db_session, refreshed) == "NEG:ABANDONO"
    assert owner_ctx.agent.mode == AgentMode.ACTIVE


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SM123")
@patch("worker.tasks.inactivity_sweep.datetime")
async def test_inactivity_sweep_closes_receptive_as_ausente(
    mock_dt,
    _mock_send,
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
):
    owner_ctx.agent.mode = AgentMode.RECEPTIVE
    await db_session.flush()

    mock_dt.now.return_value = _NOW
    warning_at = _NOW - timedelta(minutes=25)
    li = await _make_silent_li(
        db_session,
        owner_ctx,
        warning_sent_at=warning_at,
        agent_spoke_at=warning_at,
    )

    with patch("worker.tasks.inactivity_sweep.settings") as mock_settings:
        mock_settings.inactivity_warning_minutes = 20
        mock_settings.inactivity_close_minutes = 20
        stats = await _sweep_inactivity_with_session(db_session)

    assert stats["closed"] == 1
    refreshed = await db_session.get(LeadInteraction, li.id)
    assert refreshed is not None
    assert refreshed.status == "nao_atendido"
    assert await tabulacao_codigo_for(db_session, refreshed) == "NEG:AUSENTE"


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SM123")
@patch("worker.tasks.inactivity_sweep.datetime")
async def test_inactivity_sweep_does_not_close_when_client_responded_after_warning(
    mock_dt,
    _mock_send,
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
):
    mock_dt.now.return_value = _NOW
    warning_at = _NOW - timedelta(minutes=25)
    client_reply = _NOW - timedelta(minutes=5)
    li = await _make_silent_li(
        db_session,
        owner_ctx,
        warning_sent_at=warning_at,
        agent_spoke_at=warning_at,
        client_spoke_at=client_reply,
    )

    with patch("worker.tasks.inactivity_sweep.settings") as mock_settings:
        mock_settings.inactivity_warning_minutes = 20
        mock_settings.inactivity_close_minutes = 20
        stats = await _sweep_inactivity_with_session(db_session)

    assert stats["warnings_sent"] == 0
    assert stats["closed"] == 0

    refreshed = await db_session.get(LeadInteraction, li.id)
    assert refreshed is not None
    assert refreshed.status == "em_andamento"


@pytest.mark.asyncio
async def test_touch_inbound_resets_inactivity_warning(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    warning_at = _NOW - timedelta(minutes=10)
    li = await create_lead_interaction(
        db_session,
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        lifecycle_version=1,
        inactivity_warning_sent_at=warning_at,
        data_ultima_tentativa=warning_at,
    )
    await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "whatsapp",
        touch_inbound=True,
        touch_agent_message=True,
    )
    await db_session.refresh(li)
    assert li.inactivity_warning_sent_at is None


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SM123")
@patch("worker.tasks.inactivity_sweep.datetime")
async def test_inactivity_sweep_skips_lifecycle_version_zero(
    mock_dt,
    mock_send,
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
):
    mock_dt.now.return_value = _NOW
    li = await _make_silent_li(db_session, owner_ctx, lifecycle_version=0)

    with patch("worker.tasks.inactivity_sweep.settings") as mock_settings:
        mock_settings.inactivity_warning_minutes = 20
        mock_settings.inactivity_close_minutes = 20
        stats = await _sweep_inactivity_with_session(db_session)

    assert stats["warnings_sent"] == 0
    assert stats["closed"] == 0
    refreshed = await db_session.get(LeadInteraction, li.id)
    assert refreshed is not None
    assert refreshed.inactivity_warning_sent_at is None
    mock_send.assert_not_called()


@pytest.mark.asyncio
@patch("worker.tasks.inactivity_sweep.send_whatsapp_message", return_value="SM123")
@patch("worker.tasks.inactivity_sweep.datetime")
async def test_inactivity_sweep_skips_voice_channel(
    mock_dt,
    mock_send,
    owner_ctx: OwnerContext,
    db_session,
    seeded_catalog,
):
    mock_dt.now.return_value = _NOW
    li = await _make_silent_li(db_session, owner_ctx, channel="voice")

    with patch("worker.tasks.inactivity_sweep.settings") as mock_settings:
        mock_settings.inactivity_warning_minutes = 20
        mock_settings.inactivity_close_minutes = 20
        stats = await _sweep_inactivity_with_session(db_session)

    assert stats["warnings_sent"] == 0
    assert stats["closed"] == 0
    refreshed = await db_session.get(LeadInteraction, li.id)
    assert refreshed is not None
    assert refreshed.status == "em_andamento"
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_new_li_gets_lifecycle_version_one(
    owner_ctx: OwnerContext,
    db_session,
) -> None:
    record = await upsert_lead_interaction(
        db_session,
        owner_ctx.lead.id,
        owner_ctx.campaign.id,
        "telegram",
        status="pendente",
    )
    assert record.lifecycle_version == 1
