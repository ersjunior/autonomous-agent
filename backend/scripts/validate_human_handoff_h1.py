#!/usr/bin/env python3
"""Validação H-1 — handoff humano: config, wa.me ao lead, notificação ao operador."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi import HTTPException
from sqlalchemy import select

from agents.workers.intent_agent import IntentResult
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent import Agent, AgentMode
from app.models.lead import Lead
from app.models.user import User
from app.services.human_handoff import (
    exit_human_mode,
    get_human_mode_payload,
    handle_escalation_handoff,
    handle_human_mode_inbound,
    is_human_handoff_active,
    is_human_notified,
    is_in_human_mode,
)
from app.services.inbound_attendance import attend_inbound_message
from app.services.settings_service import (
    _serialize_managed_value,
    get_redis_settings_version,
    seed_missing_settings,
    set_setting_internal,
    update_settings,
)


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    status = "OK" if cond else "FALHA"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond


async def _get_receptive_agent(session):
    return (
        await session.execute(
            select(Agent).where(Agent.mode == AgentMode.RECEPTIVE).limit(1)
        )
    ).scalar_one_or_none()


async def _fixture_lead_phone(session) -> tuple[Lead, str]:
    user = (
        await session.execute(select(User).where(User.email == "admin@admin.com"))
    ).scalar_one()
    lead = (
        await session.execute(select(Lead).where(Lead.user_id == user.id).limit(1))
    ).scalar_one_or_none()
    if lead is None:
        raise RuntimeError("Nenhum lead para testes H-1")
    phone = lead.telefone_1 or "5511999887766"
    return lead, phone


async def test_settings_validation(session) -> bool:
    print("\n=== Configurações H-1 (validação + hot-reload) ===")
    await seed_missing_settings(session)
    version_before = get_redis_settings_version()

    try:
        _serialize_managed_value("human_handoff_whatsapp", "abc")
        invalid_rejected = False
    except HTTPException as exc:
        invalid_rejected = exc.status_code == 400
        print(f"  [info] rejeição esperada: {exc.detail}")

    ok = _ok("número inválido rejeitado", invalid_rejected)

    operator = "+5511988776655"
    version = await set_setting_internal(session, "human_handoff_whatsapp", operator)
    ok &= _ok("número válido salvo", settings.human_handoff_whatsapp == operator)
    ok &= _ok("settings_version incrementou", version > version_before, f"v={version}")

    await set_setting_internal(session, "human_handoff_enabled", "true")
    ok &= _ok("human_handoff_enabled=true", settings.human_handoff_enabled is True)
    ok &= _ok("is_human_handoff_active()", is_human_handoff_active())

    await set_setting_internal(session, "human_handoff_enabled", "false")
    ok &= _ok("desabilitado sem notificar", not is_human_handoff_active())

    await set_setting_internal(session, "human_handoff_enabled", "true")
    await set_setting_internal(session, "human_handoff_whatsapp", "")
    ok &= _ok("número vazio desativa handoff", not is_human_handoff_active())

    await set_setting_internal(session, "human_handoff_whatsapp", operator)
    return ok


async def test_escalation_messages(session) -> bool:
    print("\n=== Escalonamento → wa.me ao lead + notificação ao operador ===")
    lead, phone = await _fixture_lead_phone(session)
    agent = await _get_receptive_agent(session)
    if agent is None:
        return _ok("agente receptivo", False, "não encontrado")

    ch = "whatsapp"
    exit_human_mode(ch, phone)

    operator = "+5511988776655"
    await set_setting_internal(session, "human_handoff_whatsapp", operator)
    await set_setting_internal(session, "human_handoff_enabled", "true")

    lead_messages: list[str] = []
    operator_messages: list[str] = []

    async def capture_deliver(channel: str, user_id: str, text: str) -> bool:
        lead_messages.append(text)
        return True

    def capture_twilio(to: str, body: str) -> str:
        operator_messages.append(body)
        return "SM_H1_TEST"

    escalate_result = IntentResult(intent="escalate", confidence=0.99, entities={})
    with (
        patch(
            "agents.orchestrator.router.route_message",
            new_callable=AsyncMock,
            return_value={
                "response": "Vou transferir você para um atendente humano.",
                "should_escalate": True,
                "intent": "escalate",
            },
        ),
        patch(
            "app.services.inbound_attendance.deliver_channel_text",
            new_callable=AsyncMock,
            side_effect=capture_deliver,
        ),
        patch(
            "worker.tasks.inbound_handler._deliver_inbound_response",
            new_callable=AsyncMock,
            side_effect=capture_deliver,
        ),
        patch(
            "agents.channels.whatsapp.twilio_client.send_whatsapp_message",
            side_effect=capture_twilio,
        ),
        patch(
            "agents.workers.intent_agent.identify_intent",
            new_callable=AsyncMock,
            return_value=escalate_result,
        ),
    ):
        await attend_inbound_message(
            session,
            channel=ch,
            user_id=phone,
            message="quero falar com humano",
            agent=agent,
            lead=lead,
            bind_capacity=False,
        )

    ok = _ok("modo humano ativo", is_in_human_mode(ch, phone))
    payload = get_human_mode_payload(ch, phone)
    ok &= _ok("human_notified=true no Redis", bool(payload and payload.get("human_notified")))

    transfer_sent = any("transferir" in m.lower() or "atendente" in m.lower() for m in lead_messages)
    ok &= _ok("lead recebeu resposta de transferência", transfer_sent, str(lead_messages[:2]))

    wa_msg = next((m for m in lead_messages if "wa.me" in m), None)
    digits = operator.replace("+", "")
    ok &= _ok(
        "lead recebeu link wa.me",
        wa_msg is not None and digits in wa_msg.replace("+", ""),
        wa_msg or "",
    )

    op_body = operator_messages[0] if operator_messages else ""
    ok &= _ok("operador notificado", bool(op_body), "corpo abaixo")
    if op_body:
        print("  --- Notificação ao operador ---")
        print(op_body)
        print("  --- Fim notificação ---")

    print("\n=== Segunda mensagem do lead (sem re-notificar operador) ===")
    operator_messages.clear()
    handled, wait_msg = handle_human_mode_inbound(ch, phone)
    ok &= _ok("curto-circuito na 2ª msg", handled)
    ok &= _ok("sem nova notificação ao operador", len(operator_messages) == 0)

    exit_human_mode(ch, phone)
    return ok


async def test_twilio_failure_does_not_break(session) -> bool:
    print("\n=== Falha Twilio não quebra modo humano ===")
    from app.services.human_handoff import enter_human_mode

    lead, phone = await _fixture_lead_phone(session)
    ch = "whatsapp"
    exit_human_mode(ch, phone)

    await set_setting_internal(session, "human_handoff_whatsapp", "+5511988776655")
    await set_setting_internal(session, "human_handoff_enabled", "true")
    enter_human_mode(ch, phone, intent="escalate")

    with (
        patch(
            "worker.tasks.inbound_handler._deliver_inbound_response",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "agents.channels.whatsapp.twilio_client.send_whatsapp_message",
            side_effect=RuntimeError("Twilio trial blocked"),
        ),
    ):
        await handle_escalation_handoff(
            session,
            channel=ch,
            user_id=phone,
            lead=lead,
            message="preciso de ajuda humana",
            intent="escalate",
        )

    ok = _ok("human_notified após falha Twilio", is_human_notified(ch, phone))
    ok &= _ok("modo humano mantido após falha Twilio", is_in_human_mode(ch, phone))

    exit_human_mode(ch, phone)
    return ok


async def test_disabled_preserves_behavior(session) -> bool:
    print("\n=== Desabilitado → sem wa.me nem notificação ===")
    lead, phone = await _fixture_lead_phone(session)
    agent = await _get_receptive_agent(session)
    if agent is None:
        return _ok("agente receptivo", False)

    ch = "whatsapp"
    exit_human_mode(ch, phone)
    await set_setting_internal(session, "human_handoff_enabled", "false")

    lead_messages: list[str] = []
    operator_messages: list[str] = []

    with (
        patch(
            "agents.orchestrator.router.route_message",
            new_callable=AsyncMock,
            return_value={
                "response": "Transferindo para humano.",
                "should_escalate": True,
                "intent": "escalate",
            },
        ),
        patch(
            "app.services.inbound_attendance.deliver_channel_text",
            new_callable=AsyncMock,
            side_effect=lambda c, u, t: lead_messages.append(t) or True,
        ),
        patch(
            "agents.channels.whatsapp.twilio_client.send_whatsapp_message",
            side_effect=lambda to, body: operator_messages.append(body) or "SM_X",
        ),
    ):
        await attend_inbound_message(
            session,
            channel=ch,
            user_id=phone,
            message="quero humano",
            agent=agent,
            lead=lead,
            bind_capacity=False,
        )

    ok = _ok("modo humano ainda ativa", is_in_human_mode(ch, phone))
    ok &= _ok("sem wa.me ao lead", not any("wa.me" in m for m in lead_messages))
    ok &= _ok("sem notificação ao operador", len(operator_messages) == 0)

    exit_human_mode(ch, phone)
    return ok


async def main() -> int:
    print("validate_human_handoff_h1.py — entrega H-1")
    results: list[bool] = []

    async with AsyncSessionLocal() as session:
        results.append(await test_settings_validation(session))
        results.append(await test_escalation_messages(session))
        results.append(await test_twilio_failure_does_not_break(session))
        results.append(await test_disabled_preserves_behavior(session))

    passed = sum(results)
    total = len(results)
    print(f"\n=== Resumo: {passed}/{total} cenários OK ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
