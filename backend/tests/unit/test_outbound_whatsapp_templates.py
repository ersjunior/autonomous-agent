"""Unit tests — outbound WhatsApp templates no acionamento ativo (W3 fase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.whatsapp_outbound import WhatsAppSendMode
from worker.tasks.outbound_campaign import (
    DeliverResult,
    _deliver_message,
    _send_on_channel,
)

pytestmark = pytest.mark.unit

_INITIAL_SID = "HX564c9577120a14f2d7d5517c2e26982b"
_FOLLOWUP_SID = "HX6afa2ef98be8d7f1e67ef203bb751c95"


def _lead() -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.nome_cliente = "Maria"
    lead.telefone_1 = "+5511999999999"
    lead.aux_values = {}
    return lead


def _campaign() -> MagicMock:
    agent = MagicMock()
    agent.name = "Agente_Ativo"
    agent.mode.value = "ACTIVE"
    agent.description = ""
    agent.config = None
    campaign = MagicMock()
    campaign.id = uuid.uuid4()
    campaign.name = "Campanha Teste"
    campaign.agent = agent
    return campaign


def _session(*, interaction: MagicMock | None = None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = interaction
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_first_message_whatsapp_template_skips_llm_and_stores_sid() -> None:
    lead = _lead()
    campaign = _campaign()
    session = _session(interaction=None)
    template_mode = WhatsAppSendMode(
        mode="template",
        content_sid=_INITIAL_SID,
        content_variables={"1": "Maria"},
    )

    with (
        patch(
            "worker.tasks.outbound_campaign.resolve_whatsapp_send_mode",
            return_value=template_mode,
        ) as resolve_mock,
        patch(
            "worker.tasks.outbound_campaign.route_message",
            new_callable=AsyncMock,
        ) as route_mock,
        patch(
            "worker.tasks.outbound_campaign.send_whatsapp_message",
            return_value="SMtemplate001",
        ) as send_mock,
        patch(
            "worker.tasks.outbound_campaign.upsert_lead_interaction",
            new_callable=AsyncMock,
        ) as upsert_mock,
    ):
        result = await _send_on_channel(
            session,
            lead,
            campaign,
            "whatsapp",
            followup=False,
        )

    assert result is not None
    assert result["whatsapp_template"] is True
    assert result["content_sid"] == _INITIAL_SID
    assert result["response"] is None
    resolve_mock.assert_called_once()
    assert resolve_mock.call_args.args[0] == "inicial"
    route_mock.assert_not_awaited()
    send_mock.assert_called_once_with(
        lead.telefone_1,
        content_sid=_INITIAL_SID,
        content_variables={"1": "Maria"},
    )
    upsert_mock.assert_awaited_once()
    assert upsert_mock.call_args.kwargs["twilio_message_sid"] == "SMtemplate001"
    assert upsert_mock.call_args.kwargs["last_delivery_status"] == "queued"
    assert upsert_mock.call_args.kwargs["set_acionamento"] is True
    assert upsert_mock.call_args.kwargs["record_outbound_attempt"] is True


@pytest.mark.asyncio
async def test_followup_whatsapp_template_uses_followup_sid() -> None:
    lead = _lead()
    campaign = _campaign()
    interaction = MagicMock()
    interaction.data_ultimo_contato = None
    session = _session(interaction=interaction)
    template_mode = WhatsAppSendMode(
        mode="template",
        content_sid=_FOLLOWUP_SID,
        content_variables={"1": "Maria"},
    )

    with (
        patch(
            "worker.tasks.outbound_campaign.resolve_whatsapp_send_mode",
            return_value=template_mode,
        ) as resolve_mock,
        patch("worker.tasks.outbound_campaign.route_message", new_callable=AsyncMock) as route_mock,
        patch(
            "worker.tasks.outbound_campaign.send_whatsapp_message",
            return_value="SMfollow001",
        ) as send_mock,
        patch(
            "worker.tasks.outbound_campaign.upsert_lead_interaction",
            new_callable=AsyncMock,
        ) as upsert_mock,
    ):
        result = await _send_on_channel(
            session,
            lead,
            campaign,
            "whatsapp",
            followup=True,
        )

    assert result is not None
    assert result["followup"] is True
    resolve_mock.assert_called_once()
    assert resolve_mock.call_args.args[0] == "followup"
    route_mock.assert_not_awaited()
    send_mock.assert_called_once_with(
        lead.telefone_1,
        content_sid=_FOLLOWUP_SID,
        content_variables={"1": "Maria"},
    )
    assert upsert_mock.call_args.kwargs["devolutiva"] == "template:followup"
    assert upsert_mock.call_args.kwargs["set_acionamento"] is False


@pytest.mark.asyncio
async def test_templates_off_keeps_llm_freeform_flow() -> None:
    lead = _lead()
    campaign = _campaign()
    session = _session(interaction=None)

    with (
        patch(
            "worker.tasks.outbound_campaign.resolve_whatsapp_send_mode",
            return_value=WhatsAppSendMode(mode="freeform"),
        ),
        patch(
            "worker.tasks.outbound_campaign.route_message",
            new_callable=AsyncMock,
            return_value={"response": "Olá do LLM"},
        ) as route_mock,
        patch(
            "worker.tasks.outbound_campaign.send_whatsapp_message",
            return_value="SMfree001",
        ) as send_mock,
        patch(
            "worker.tasks.outbound_campaign.upsert_lead_interaction",
            new_callable=AsyncMock,
        ),
    ):
        result = await _send_on_channel(
            session,
            lead,
            campaign,
            "whatsapp",
            followup=False,
        )

    assert result is not None
    assert result["whatsapp_template"] is False
    assert result["response"] == "Olá do LLM"
    route_mock.assert_awaited_once()
    send_mock.assert_called_once_with(lead.telefone_1, "Olá do LLM")


@pytest.mark.asyncio
async def test_inside_24h_window_uses_freeform_even_when_templates_configured() -> None:
    lead = _lead()
    campaign = _campaign()
    interaction = MagicMock()
    interaction.data_ultimo_contato = datetime.now(timezone.utc)
    session = _session(interaction=interaction)

    with (
        patch(
            "worker.tasks.outbound_campaign.resolve_whatsapp_send_mode",
            return_value=WhatsAppSendMode(mode="freeform"),
        ),
        patch(
            "worker.tasks.outbound_campaign.route_message",
            new_callable=AsyncMock,
            return_value={"response": "Resposta conversacional"},
        ) as route_mock,
        patch(
            "worker.tasks.outbound_campaign.send_whatsapp_message",
            return_value="SMwin001",
        ),
        patch(
            "worker.tasks.outbound_campaign.upsert_lead_interaction",
            new_callable=AsyncMock,
        ),
    ):
        result = await _send_on_channel(
            session,
            lead,
            campaign,
            "whatsapp",
            followup=False,
        )

    assert result is not None
    assert result["whatsapp_template"] is False
    route_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_message_whatsapp_template_path() -> None:
    lead = _lead()
    campaign = _campaign()
    session = AsyncMock()

    with patch(
        "worker.tasks.outbound_campaign.send_whatsapp_message",
        return_value="SMdeliverTpl",
    ) as send_mock:
        result = await _deliver_message(
            session,
            lead,
            campaign,
            "whatsapp",
            "+5511999999999",
            response=None,
            content_sid=_INITIAL_SID,
            content_variables={"1": "Maria"},
        )

    assert result == DeliverResult(
        ok=True,
        twilio_message_sid="SMdeliverTpl",
        initial_delivery_status="queued",
    )
    send_mock.assert_called_once_with(
        "+5511999999999",
        content_sid=_INITIAL_SID,
        content_variables={"1": "Maria"},
    )


def test_resolve_whatsapp_send_mode_sandbox_is_freeform() -> None:
    from app.core.config import Settings

    s = Settings()
    s.whatsapp_use_templates = True
    s.whatsapp_template_mode = "auto"
    s.twilio_phone_number = "+14155238886"

    with patch("app.services.whatsapp_outbound.settings", s):
        from app.services.whatsapp_outbound import resolve_whatsapp_send_mode

        mode = resolve_whatsapp_send_mode("inicial", None, lead=_lead())

    assert mode.mode == "freeform"


@pytest.mark.asyncio
async def test_send_test_dispatch_forces_whatsapp_template_within_24h() -> None:
    """Test-dispatch ignora janela 24h e envia template (dict, sem LLM)."""
    from datetime import datetime, timezone

    from worker.tasks.outbound_campaign import _send_test_dispatch

    lead = _lead()
    lead.nome_cliente = "Eliezer Ramos Silveira Junior"
    campaign = _campaign()
    session = AsyncMock()

    record = MagicMock()
    record.data_ultimo_contato = datetime.now(timezone.utc)
    template_mode = WhatsAppSendMode(
        mode="template",
        content_sid=_INITIAL_SID,
        content_variables={"1": "Eliezer Ramos Silveira Junior"},
    )

    with (
        patch(
            "worker.tasks.outbound_campaign._fetch_lead_interaction",
            new=AsyncMock(return_value=record),
        ),
        patch(
            "worker.tasks.outbound_campaign.resolve_whatsapp_send_mode",
            return_value=template_mode,
        ) as resolve_mock,
        patch(
            "worker.tasks.outbound_campaign.send_whatsapp_message",
            return_value="SMtestTpl",
        ) as send_mock,
        patch(
            "worker.tasks.outbound_campaign.route_message",
            new=AsyncMock(),
        ) as route_mock,
        patch(
            "worker.tasks.outbound_campaign.upsert_lead_interaction",
            new=AsyncMock(),
        ),
    ):
        result = await _send_test_dispatch(
            session,
            lead,
            campaign,
            "whatsapp",
            campaign.agent,
        )

    assert result["error"] is None
    route_mock.assert_not_awaited()
    resolve_mock.assert_called_once()
    assert resolve_mock.call_args.kwargs["ignore_service_window"] is True
    send_mock.assert_called_once_with(
        lead.telefone_1,
        content_sid=_INITIAL_SID,
        content_variables={"1": "Eliezer Ramos Silveira Junior"},
    )
