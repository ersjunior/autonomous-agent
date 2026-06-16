"""Camada 3 — activation API: channel-settings, start/stop por canal, history, finalize, test-dispatch."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select

from app.core.activation_defaults import SUPPORTED_CHANNEL_TYPES
from app.core.authorization import SYSTEM_RECORD_EDIT_DETAIL
from app.models.agent import Agent, AgentMode
from app.models.agent_channel_settings import AgentChannelSettings
from tests.api.ownership_helpers import (
    foreign_agent_id,
    foreign_campaign_id,
    foreign_lead_id,
    foreign_owner_context,
)
from tests.integration.helpers import (
    OwnerContext,
    create_activation_records,
    create_lead_interaction,
    tabulacao_codigo_for,
    get_admin_user,
)
from tests.integration.helpers import add_campaign_channel, add_lead_base_channel

pytestmark = pytest.mark.api

AGENTS = "/api/v1/agents"
CAMPAIGNS = "/api/v1/campaigns"
ACTIVATION = "/api/v1/activation"

BASE_TIME = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)

MESSAGING_PARAMS = {
    "chats_simultaneos": 8,
    "campanhas_simultaneas": 2,
    "tentativas_sem_resposta": 2,
    "minutos_segunda_mensagem": 20,
    "horario_inicio": "00:00",
    "horario_fim": "23:59",
    "receptivo_horario_inicio": "00:00",
    "receptivo_horario_fim": "23:59",
}


async def _system_agent_id(db_session) -> uuid.UUID:
    admin = await get_admin_user(db_session)
    agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Ativo",
            )
        )
    ).scalar_one()
    return agent.id


async def _receptive_system_agent_id(db_session) -> uuid.UUID:
    admin = await get_admin_user(db_session)
    agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Receptivo",
            )
        )
    ).scalar_one()
    return agent.id


async def _prepare_activation_campaign(db_session, owner_ctx: OwnerContext) -> None:
    await add_campaign_channel(db_session, owner_ctx.campaign.id, "whatsapp")
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    owner_ctx.agent.mode = AgentMode.ACTIVE
    await db_session.flush()


@pytest.fixture
def mock_activation_channel_dispatch(monkeypatch):
    """Evita Celery no start por canal (dispatch_campaign_leads_for_channel)."""
    state: dict = {"calls": []}

    def fake_delay(lead_id: str, campaign_id: str, channel_type: str | None = None) -> None:
        state["calls"].append((lead_id, campaign_id, channel_type))

    monkeypatch.setattr(
        "app.services.activation_service.send_campaign_message.delay",
        fake_delay,
    )
    return state


@pytest.fixture
def mock_test_dispatch_stack(monkeypatch):
    """Sem Ollama nem Twilio/Telegram reais no test-dispatch."""
    from app.core.config import settings

    # Isola do .env: contrato legado testa caminho freeform (LLM + _deliver_message mock).
    monkeypatch.setattr(settings, "whatsapp_use_templates", False)

    state: dict = {"route_calls": [], "deliver_calls": []}

    async def fake_route_message(prompt, channel, recipient, **kwargs):
        state["route_calls"].append(
            {"prompt": prompt, "channel": channel, "recipient": recipient}
        )
        return {"response": "Resposta mock de test-dispatch"}

    async def fake_deliver_message(*args, **kwargs):
        from worker.tasks.outbound_campaign import DeliverResult

        state["deliver_calls"].append(args[:4])
        return DeliverResult(
            ok=True,
            twilio_message_sid="SMmock-test-dispatch",
            initial_delivery_status="queued",
        )

    monkeypatch.setattr("worker.tasks.outbound_campaign.route_message", fake_route_message)
    monkeypatch.setattr(
        "worker.tasks.outbound_campaign._deliver_message",
        fake_deliver_message,
    )
    return state


# --- Channel-settings ---


async def test_channel_settings_list_returns_200_with_channels(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(f"{AGENTS}/{owner_ctx.agent.id}/channel-settings")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == str(owner_ctx.agent.id)
    assert body["is_system"] is False
    assert body["editable"] is True
    channel_types = {ch["channel_type"] for ch in body["channels"]}
    assert channel_types == set(SUPPORTED_CHANNEL_TYPES)
    for ch in body["channels"]:
        assert ch["editable"] is True
        assert ch["is_system"] is False
        assert isinstance(ch["params"], dict)


async def test_channel_settings_list_foreign_agent_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = await foreign_agent_id(db_session)
    response = await auth_client.get(f"{AGENTS}/{foreign_id}/channel-settings")
    assert response.status_code == 404


async def test_channel_settings_get_single_returns_200(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/whatsapp"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["channel_type"] == "whatsapp"
    assert "chats_simultaneos" in body["params"]


async def test_channel_settings_get_invalid_channel_returns_400(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.get(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/email"
    )
    assert response.status_code == 400
    assert "Unsupported channel type" in response.json()["detail"]


async def test_channel_settings_put_persists_changes(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    response = await auth_client.put(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/whatsapp",
        json={"params": MESSAGING_PARAMS},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["params"]["chats_simultaneos"] == 8
    assert body["params"]["horario_inicio"] == "00:00"

    row = (
        await db_session.execute(
            select(AgentChannelSettings).where(
                AgentChannelSettings.agent_id == owner_ctx.agent.id,
                AgentChannelSettings.channel_type == "whatsapp",
            )
        )
    ).scalar_one()
    assert row.params["chats_simultaneos"] == 8


async def test_channel_settings_put_system_agent_returns_403(
    auth_client,
    system_seeds,
    db_session,
) -> None:
    system_id = await _system_agent_id(db_session)
    response = await auth_client.put(
        f"{AGENTS}/{system_id}/channel-settings/whatsapp",
        json={"params": MESSAGING_PARAMS},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == SYSTEM_RECORD_EDIT_DETAIL


async def test_channel_settings_put_invalid_channel_returns_400(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.put(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/invalid",
        json={"params": MESSAGING_PARAMS},
    )
    assert response.status_code == 400


async def test_channel_settings_put_foreign_agent_returns_404(
    auth_client,
    db_session,
) -> None:
    foreign_id = await foreign_agent_id(db_session)
    response = await auth_client.put(
        f"{AGENTS}/{foreign_id}/channel-settings/whatsapp",
        json={"params": MESSAGING_PARAMS},
    )
    assert response.status_code == 404


async def test_channel_settings_put_empty_params_returns_422(
    auth_client,
    owner_ctx,
) -> None:
    response = await auth_client.put(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/whatsapp",
        json={"params": {}},
    )
    assert response.status_code == 422


async def test_channel_settings_put_invalid_time_returns_400(
    auth_client,
    owner_ctx,
) -> None:
    bad = {**MESSAGING_PARAMS, "horario_inicio": "25:00"}
    response = await auth_client.put(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/whatsapp",
        json={"params": bad},
    )
    assert response.status_code == 400


# --- Activations start/stop por canal ---


async def test_activations_list_returns_200_per_channel(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await _prepare_activation_campaign(db_session, owner_ctx)
    response = await auth_client.get(
        f"{CAMPAIGNS}/{owner_ctx.campaign.id}/activations"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["campaign_id"] == str(owner_ctx.campaign.id)
    assert len(body["activations"]) == 1
    assert body["activations"][0]["channel_type"] == "whatsapp"
    assert body["activations"][0]["is_running"] is False


async def test_activation_start_returns_200_and_dispatches(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_activation_channel_dispatch,
) -> None:
    await _prepare_activation_campaign(db_session, owner_ctx)
    await auth_client.put(
        f"{AGENTS}/{owner_ctx.agent.id}/channel-settings/whatsapp",
        json={"params": MESSAGING_PARAMS},
    )
    campaign_id = owner_ctx.campaign.id

    response = await auth_client.post(
        f"{CAMPAIGNS}/{campaign_id}/activations/whatsapp/start"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "started"
    assert body["channel_type"] == "whatsapp"
    assert body["dispatched_now"] == 1
    assert body["leads_dispatched"] == 1
    assert body["activation"]["is_running"] is True
    assert len(mock_activation_channel_dispatch["calls"]) == 1
    assert mock_activation_channel_dispatch["calls"][0][2] == "whatsapp"


async def test_activation_start_non_active_agent_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_activation_channel_dispatch,
) -> None:
    await _prepare_activation_campaign(db_session, owner_ctx)
    owner_ctx.agent.mode = AgentMode.RECEPTIVE
    await db_session.flush()

    response = await auth_client.post(
        f"{CAMPAIGNS}/{owner_ctx.campaign.id}/activations/whatsapp/start"
    )
    assert response.status_code == 400
    assert "ACTIVE" in response.json()["detail"]
    assert mock_activation_channel_dispatch["calls"] == []


async def test_activation_start_channel_not_on_campaign_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_activation_channel_dispatch,
) -> None:
    await add_campaign_channel(db_session, owner_ctx.campaign.id, "telegram")
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")

    response = await auth_client.post(
        f"{CAMPAIGNS}/{owner_ctx.campaign.id}/activations/whatsapp/start"
    )
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]
    assert mock_activation_channel_dispatch["calls"] == []


async def test_activation_start_outside_window_skips_dispatch(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_activation_channel_dispatch,
    monkeypatch,
) -> None:
    await _prepare_activation_campaign(db_session, owner_ctx)
    monkeypatch.setattr("app.api.v1.activation.is_within_window", lambda *_a, **_k: False)

    response = await auth_client.post(
        f"{CAMPAIGNS}/{owner_ctx.campaign.id}/activations/whatsapp/start"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["activation"]["is_running"] is True
    assert body["dispatched_now"] == 0
    assert body["reason"] is not None
    assert mock_activation_channel_dispatch["calls"] == []


async def test_activation_stop_returns_200(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_activation_channel_dispatch,
) -> None:
    await _prepare_activation_campaign(db_session, owner_ctx)
    campaign_id = owner_ctx.campaign.id
    start = await auth_client.post(f"{CAMPAIGNS}/{campaign_id}/activations/whatsapp/start")
    assert start.status_code == 200

    response = await auth_client.post(f"{CAMPAIGNS}/{campaign_id}/activations/whatsapp/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["is_running"] is False
    assert body["channel_type"] == "whatsapp"


async def test_activation_start_foreign_campaign_returns_404(
    auth_client,
    db_session,
    clean_redis,
    mock_activation_channel_dispatch,
) -> None:
    foreign_id = await foreign_campaign_id(db_session)
    response = await auth_client.post(
        f"{CAMPAIGNS}/{foreign_id}/activations/whatsapp/start"
    )
    assert response.status_code == 404
    assert mock_activation_channel_dispatch["calls"] == []


async def test_activation_stop_foreign_campaign_returns_404(
    auth_client,
    db_session,
    clean_redis,
) -> None:
    foreign_id = await foreign_campaign_id(db_session)
    response = await auth_client.post(
        f"{CAMPAIGNS}/{foreign_id}/activations/whatsapp/stop"
    )
    assert response.status_code == 404


# --- Activation history ---


async def test_activation_history_returns_200_paginated(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 5, base_time=BASE_TIME)
    response = await auth_client.get(f"{ACTIVATION}/history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert body["skip"] == 0
    assert body["limit"] == 50


async def test_activation_history_filter_by_campaign(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)
    response = await auth_client.get(
        f"{ACTIVATION}/history",
        params={"campaign_id": str(owner_ctx.campaign.id)},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3


async def test_activation_history_filter_by_channel(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, channel_type="whatsapp"
    )
    await create_activation_records(
        db_session, owner_ctx, 3, base_time=BASE_TIME, channel_type="telegram"
    )
    response = await auth_client.get(
        f"{ACTIVATION}/history",
        params={"channel_type": "telegram"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert all(item["channel_type"] == "telegram" for item in body["items"])


async def test_activation_history_filter_by_status(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, status="convertido"
    )
    await create_activation_records(
        db_session, owner_ctx, 3, base_time=BASE_TIME, status="em_andamento"
    )
    response = await auth_client.get(
        f"{ACTIVATION}/history",
        params={"status": "convertido"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_activation_history_open_only_excludes_terminal(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(
        db_session, owner_ctx, 2, base_time=BASE_TIME, status="convertido"
    )
    await create_activation_records(
        db_session, owner_ctx, 4, base_time=BASE_TIME, status="em_andamento"
    )
    response = await auth_client.get(
        f"{ACTIVATION}/history",
        params={"open_only": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert all(not item["is_terminal"] for item in body["items"])


async def test_activation_history_invalid_skip_returns_400(
    auth_client,
) -> None:
    response = await auth_client.get(f"{ACTIVATION}/history", params={"skip": -1})
    assert response.status_code == 400


async def test_activation_history_invalid_limit_returns_400(
    auth_client,
) -> None:
    for bad_limit in (0, 201):
        response = await auth_client.get(
            f"{ACTIVATION}/history",
            params={"limit": bad_limit},
        )
        assert response.status_code == 400


async def test_activation_history_ownership_isolates_tenants(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    await create_activation_records(db_session, owner_ctx, 3, base_time=BASE_TIME)
    other_ctx = await foreign_owner_context(db_session, suffix="hist-other")
    await create_activation_records(db_session, other_ctx, 2, base_time=BASE_TIME)

    response = await auth_client.get(f"{ACTIVATION}/history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3


# --- Finalize ---


async def test_finalize_interaction_returns_200_and_persists(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_capacity_release,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.activation_history.is_in_human_mode",
        lambda _c, _u: False,
    )
    records = await create_activation_records(
        db_session, owner_ctx, 1, base_time=BASE_TIME, status="em_andamento"
    )
    li_id = records[0].id

    response = await auth_client.post(
        f"{ACTIVATION}/interactions/{li_id}/finalize",
        json={"tabulacao_codigo": "NEG:SUCESSO"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "convertido"
    assert body["tabulacao_codigo"] == "NEG:SUCESSO"

    await db_session.refresh(records[0])
    assert records[0].status == "convertido"
    assert await tabulacao_codigo_for(db_session, records[0]) == "NEG:SUCESSO"
    assert len(mock_capacity_release["outbound_calls"]) == 1


async def test_finalize_foreign_interaction_returns_404(
    auth_client,
    db_session,
) -> None:
    other_ctx = await foreign_owner_context(db_session, suffix="fin-foreign")
    li = await create_lead_interaction(
        db_session,
        lead_id=other_ctx.lead.id,
        campaign_id=other_ctx.campaign.id,
        status="em_andamento",
        data_acionamento=BASE_TIME,
    )
    response = await auth_client.post(
        f"{ACTIVATION}/interactions/{li.id}/finalize",
        json={"tabulacao_codigo": "NEG:SUCESSO"},
    )
    assert response.status_code == 404


async def test_finalize_missing_tabulacao_returns_422(
    auth_client,
    owner_ctx,
    db_session,
) -> None:
    records = await create_activation_records(
        db_session, owner_ctx, 1, base_time=BASE_TIME, status="em_andamento"
    )
    response = await auth_client.post(
        f"{ACTIVATION}/interactions/{records[0].id}/finalize",
        json={},
    )
    assert response.status_code == 422


async def test_finalize_invalid_tabulacao_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.activation_history.is_in_human_mode",
        lambda _c, _u: False,
    )
    records = await create_activation_records(
        db_session, owner_ctx, 1, base_time=BASE_TIME, status="em_andamento"
    )
    response = await auth_client.post(
        f"{ACTIVATION}/interactions/{records[0].id}/finalize",
        json={"tabulacao_codigo": "NEG:INEXISTENTE"},
    )
    assert response.status_code == 400
    assert "Tabulação inválida" in response.json()["detail"]


async def test_finalize_already_terminal_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    mock_capacity_release,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.activation_history.is_in_human_mode",
        lambda _c, _u: False,
    )
    records = await create_activation_records(
        db_session, owner_ctx, 1, base_time=BASE_TIME, status="convertido"
    )
    response = await auth_client.post(
        f"{ACTIVATION}/interactions/{records[0].id}/finalize",
        json={"tabulacao_codigo": "NEG:SUCESSO"},
    )
    assert response.status_code == 400
    assert "encerrado" in response.json()["detail"].lower()


# --- Test-dispatch ---


async def test_test_dispatch_success_returns_contract(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_test_dispatch_stack,
) -> None:
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(owner_ctx.agent.id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sucesso"
    assert body["channel"] == "whatsapp"
    assert body["recipient"] == "5511999887766"
    assert body["response"] == "Resposta mock de test-dispatch"
    assert body["error"] is None
    assert body["lead_interaction_id"] is not None
    assert len(mock_test_dispatch_stack["route_calls"]) == 1
    assert len(mock_test_dispatch_stack["deliver_calls"]) == 1


async def test_test_dispatch_whatsapp_template_skips_llm_and_passes_dict_variables(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    monkeypatch,
) -> None:
    """Com templates ON, test-dispatch força template mesmo dentro da janela 24h."""
    import json
    from unittest.mock import AsyncMock

    from agents.channels.whatsapp.twilio_client import encode_content_variables
    from app.models.lead_interaction import LeadInteraction

    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    owner_ctx.lead.nome_cliente = "Eliezer Ramos Silveira Junior"
    await db_session.flush()

    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="nao_atendido",
        data_ultimo_contato=datetime.now(timezone.utc),
    )
    db_session.add(li)
    await db_session.flush()

    send_calls: list[dict] = []

    def fake_send_whatsapp(
        to: str,
        body: str | None = None,
        *,
        content_sid: str | None = None,
        content_variables: dict | None = None,
    ) -> str:
        send_calls.append(
            {
                "to": to,
                "body": body,
                "content_sid": content_sid,
                "content_variables": content_variables,
            }
        )
        return "SMmock-template-test"

    route_mock = AsyncMock()
    monkeypatch.setattr(
        "worker.tasks.outbound_campaign.send_whatsapp_message",
        fake_send_whatsapp,
    )
    monkeypatch.setattr("worker.tasks.outbound_campaign.route_message", route_mock)

    from app.core.config import settings

    monkeypatch.setattr(settings, "whatsapp_use_templates", True)
    monkeypatch.setattr(settings, "whatsapp_template_mode", "production")
    monkeypatch.setattr(settings, "twilio_phone_number", "+551150399542")

    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(owner_ctx.agent.id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sucesso"
    route_mock.assert_not_awaited()
    assert len(send_calls) == 1
    assert send_calls[0]["content_sid"]
    assert send_calls[0]["content_variables"] == {
        "1": "Eliezer Ramos Silveira Junior",
    }
    encoded = encode_content_variables(send_calls[0]["content_variables"])
    assert json.loads(encoded) == {"1": "Eliezer Ramos Silveira Junior"}


async def test_test_dispatch_dispatch_exception_returns_200_with_error(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    monkeypatch,
) -> None:
    """Falha no LLM/entrega retorna 200 + status=erro (não HTTP 500 após rollback)."""
    from app.core.config import settings

    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    err_msg = (
        "Client error '404 Not Found' for url 'http://ollama:11434/api/chat'"
    )

    # Garante caminho freeform (route_message é chamado); evita vazamento do .env.
    monkeypatch.setattr(settings, "whatsapp_use_templates", False)

    async def failing_route_message(*_args, **_kwargs):
        raise RuntimeError(err_msg)

    monkeypatch.setattr(
        "worker.tasks.outbound_campaign.route_message",
        failing_route_message,
    )

    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(owner_ctx.agent.id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "erro"
    assert body["channel"] == "whatsapp"
    assert body["recipient"] == "5511999887766"
    assert err_msg in body["error"]
    assert body["response"] is None
    assert body["lead_interaction_id"] is None


async def test_test_dispatch_receptive_agent_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    system_seeds,
    clean_redis,
    mock_test_dispatch_stack,
) -> None:
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    receptive_id = await _receptive_system_agent_id(db_session)
    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(receptive_id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 400
    assert "ACTIVE" in response.json()["detail"]
    assert mock_test_dispatch_stack["route_calls"] == []


async def test_test_dispatch_lead_without_recipient_returns_400(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_test_dispatch_stack,
) -> None:
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    owner_ctx.lead.telefone_1 = None
    owner_ctx.lead.telefone_2 = None
    await db_session.flush()

    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(owner_ctx.agent.id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 400
    assert "telefone" in response.json()["detail"].lower()
    assert mock_test_dispatch_stack["route_calls"] == []


async def test_test_dispatch_capacity_full_returns_503(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_test_dispatch_stack,
    monkeypatch,
) -> None:
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    monkeypatch.setattr(
        "app.api.v1.activation.try_acquire_outbound_capacity",
        lambda *_a, **_k: None,
    )
    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(owner_ctx.agent.id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 503
    assert "Capacidade" in response.json()["detail"]
    assert mock_test_dispatch_stack["route_calls"] == []


async def test_test_dispatch_foreign_agent_returns_404(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_test_dispatch_stack,
) -> None:
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")
    foreign_id = await foreign_agent_id(db_session)
    payload = {
        "lead_id": str(owner_ctx.lead.id),
        "agent_id": str(foreign_id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 404
    assert mock_test_dispatch_stack["route_calls"] == []


async def test_test_dispatch_foreign_lead_returns_404(
    auth_client,
    owner_ctx,
    db_session,
    clean_redis,
    mock_test_dispatch_stack,
) -> None:
    foreign_lead = await foreign_lead_id(db_session)
    payload = {
        "lead_id": str(foreign_lead),
        "agent_id": str(owner_ctx.agent.id),
        "channel_type": "whatsapp",
    }
    response = await auth_client.post(f"{ACTIVATION}/test-dispatch", json=payload)
    assert response.status_code == 404
    assert mock_test_dispatch_stack["route_calls"] == []
