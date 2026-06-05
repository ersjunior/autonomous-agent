#!/usr/bin/env python3
"""Validação B-2 — modo humano (handoff) após escalonamento."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from agents.workers.intent_agent import IntentResult
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.models.user import User
from app.services.human_handoff import (
    HUMAN_MODE_WAIT_MESSAGE,
    enter_human_mode,
    exit_human_mode,
    handle_human_mode_inbound,
    is_in_human_mode,
    should_send_waiting_message,
)
from app.services.inbound_attendance import attend_inbound_message
from worker.tasks.lead_tracking import track_inbound_lead_interaction


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    status = "OK" if cond else "FALHA"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond


async def _get_receptive_agent(session):
    from app.models.agent import Agent, AgentMode

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
        raise RuntimeError("Nenhum lead para testes B-2")
    phone = lead.telefone_1 or "5511999887766"
    return lead, phone


async def test_escalation_enters_human_mode(session) -> bool:
    print("\n=== Escalonamento → modo humano + NEG:ESCALADO ===")
    lead, phone = await _fixture_lead_phone(session)
    agent = await _get_receptive_agent(session)
    if agent is None:
        return _ok("agente receptivo", False, "não encontrado")

    ch = "whatsapp"
    exit_human_mode(ch, phone)

    async def fake_identify(msg: str, history: list) -> IntentResult:
        return IntentResult(intent="escalate", confidence=0.95, entities={})

    deliver = AsyncMock(return_value=True)
    with patch("agents.orchestrator.graph.run_identify_intent", new=AsyncMock(side_effect=fake_identify)):
        with patch("app.services.inbound_attendance.deliver_channel_text", new=deliver):
            result_text = await attend_inbound_message(
                session,
                channel=ch,
                user_id=phone,
                message="quero falar com um humano",
                agent=agent,
                lead=lead,
                bind_capacity=False,
            )

    await session.commit()
    li = (
        await session.execute(
            select(LeadInteraction)
            .where(LeadInteraction.lead_id == lead.id, LeadInteraction.channel_type == ch)
            .options(selectinload(LeadInteraction.tabulacao))
            .order_by(LeadInteraction.data_ultimo_contato.desc().nulls_last())
            .limit(1)
        )
    ).scalar_one_or_none()

    codigo = li.tabulacao.codigo if li and li.tabulacao else None
    ok = True
    ok &= _ok("resposta de transferência", "humano" in (result_text or "").lower() or "atendente" in (result_text or "").lower())
    ok &= _ok("is_in_human_mode", is_in_human_mode(ch, phone))
    ok &= _ok("NEG:ESCALADO", codigo == "NEG:ESCALADO", f"codigo={codigo}")
    exit_human_mode(ch, phone)
    return ok


async def test_short_circuit_no_llm(session) -> bool:
    print("\n=== Modo humano: curto-circuito sem LLM + msg ocasional ===")
    ch = "telegram"
    uid = f"B2SC-{uuid.uuid4().hex[:8]}"
    exit_human_mode(ch, uid)
    enter_human_mode(ch, uid)

    route_mock = AsyncMock()
    deliver = AsyncMock(return_value=True)

    agent = await _get_receptive_agent(session)
    with patch("app.services.inbound_attendance.route_message", new=route_mock):
        with patch("app.services.inbound_attendance.deliver_channel_text", new=deliver):
            text1 = await attend_inbound_message(
                session,
                channel=ch,
                user_id=uid,
                message="ainda estou esperando",
                agent=agent,
                lead=None,
                bind_capacity=False,
            )

    ok = True
    ok &= _ok("route_message NÃO chamado", route_mock.await_count == 0)
    ok &= _ok("msg ocasional enviada", deliver.await_count == 1)
    ok &= _ok("texto = wait message", text1 == HUMAN_MODE_WAIT_MESSAGE)

    with patch("app.services.inbound_attendance.route_message", new=route_mock):
        with patch("app.services.inbound_attendance.deliver_channel_text", new=deliver):
            text2 = await attend_inbound_message(
                session,
                channel=ch,
                user_id=uid,
                message="outra mensagem logo em seguida",
                agent=agent,
                lead=None,
                bind_capacity=False,
            )

    ok &= _ok("2ª msg: route ainda não chamado", route_mock.await_count == 0)
    ok &= _ok("2ª msg: sem nova entrega (throttle)", deliver.await_count == 1)
    ok &= _ok("2ª msg: retorno vazio", text2 == "")

    exit_human_mode(ch, uid)
    return ok


async def test_manual_reactivate(session) -> bool:
    print("\n=== Reativação manual ===")
    ch = "whatsapp"
    uid = f"B2RE-{uuid.uuid4().hex[:8]}"
    enter_human_mode(ch, uid)
    ok = _ok("em modo humano", is_in_human_mode(ch, uid))
    exit_human_mode(ch, uid)
    ok &= _ok("após reactivate", not is_in_human_mode(ch, uid))

    agent = await _get_receptive_agent(session)
    route_mock = AsyncMock(
        return_value={
            "response": "Olá, posso ajudar.",
            "intent": "greeting",
            "should_escalate": False,
        }
    )
    deliver = AsyncMock(return_value=True)
    with patch("app.services.inbound_attendance.route_message", new=route_mock):
        with patch("app.services.inbound_attendance.deliver_channel_text", new=deliver):
            await attend_inbound_message(
                session,
                channel=ch,
                user_id=uid,
                message="oi, voltei",
                agent=agent,
                lead=None,
                bind_capacity=False,
            )
    ok &= _ok("próxima msg atendida pelo bot", route_mock.await_count == 1)
    return ok


async def test_ttl_expiry(session) -> bool:
    print("\n=== TTL expira → volta ao bot ===")
    ch = "telegram"
    uid = f"B2TTL-{uuid.uuid4().hex[:8]}"
    exit_human_mode(ch, uid)

    original_ttl = settings.human_handoff_finalize_ttl_seconds
    settings.human_handoff_finalize_ttl_seconds = 2
    try:
        enter_human_mode(ch, uid)
        ok = _ok("modo humano ativo", is_in_human_mode(ch, uid))
        time.sleep(3)
        ok &= _ok("TTL Redis expirou (finalize_ttl)", not is_in_human_mode(ch, uid))

        agent = await _get_receptive_agent(session)
        route_mock = AsyncMock(
            return_value={
                "response": "Atendimento retomado.",
                "intent": "question",
                "should_escalate": False,
            }
        )
        with patch("app.services.inbound_attendance.route_message", new=route_mock):
            with patch("app.services.inbound_attendance.deliver_channel_text", new=AsyncMock()):
                await attend_inbound_message(
                    session,
                    channel=ch,
                    user_id=uid,
                    message="ainda preciso de ajuda",
                    agent=agent,
                    lead=None,
                    bind_capacity=False,
                )
        ok &= _ok("bot atende após TTL", route_mock.await_count == 1)
    finally:
        settings.human_handoff_finalize_ttl_seconds = original_ttl
        exit_human_mode(ch, uid)
    return ok


async def test_normal_contact_unaffected(session) -> bool:
    print("\n=== Contato normal (sem modo humano) ===")
    ch = "telegram"
    uid = f"B2NORM-{uuid.uuid4().hex[:8]}"
    exit_human_mode(ch, uid)
    agent = await _get_receptive_agent(session)

    route_mock = AsyncMock(
        return_value={
            "response": "Resposta normal.",
            "intent": "question",
            "should_escalate": False,
        }
    )
    with patch("app.services.inbound_attendance.route_message", new=route_mock):
        with patch("app.services.inbound_attendance.deliver_channel_text", new=AsyncMock()):
            await attend_inbound_message(
                session,
                channel=ch,
                user_id=uid,
                message="qual o horário?",
                agent=agent,
                lead=None,
                bind_capacity=False,
            )
    ok = _ok("atendimento normal", route_mock.await_count == 1)
    ok &= _ok("não entrou em modo humano", not is_in_human_mode(ch, uid))
    return ok


async def test_process_receptive_skips_queue(session) -> bool:
    print("\n=== Receptivo em modo humano: não enfileira ===")
    from app.services.inbound_attendance import process_receptive_inbound

    ch = "whatsapp"
    uid = f"B2Q-{uuid.uuid4().hex[:8]}"
    enter_human_mode(ch, uid)
    agent = await _get_receptive_agent(session)

    enqueue_mock = MagicMock()
    capacity_mock = MagicMock(return_value=MagicMock())
    deliver = AsyncMock(return_value=True)

    with patch("app.services.inbound_attendance.enqueue_receptive", new=enqueue_mock):
        with patch(
            "app.services.inbound_attendance.try_acquire_receptive_capacity",
            new=capacity_mock,
        ):
            with patch("app.services.inbound_attendance.deliver_channel_text", new=deliver):
                with patch(
                    "app.services.inbound_attendance.is_receptive_window_open",
                    return_value=True,
                ):
                    with patch(
                        "app.services.inbound_attendance.merged_receptive_params",
                        new=AsyncMock(return_value={}),
                    ):
                        text = await process_receptive_inbound(
                            session,
                            channel=ch,
                            user_id=uid,
                            message="estou na fila humana",
                            agent=agent,
                            lead=None,
                        )

    ok = True
    ok &= _ok("enqueue NÃO chamado", enqueue_mock.call_count == 0)
    ok &= _ok("capacity NÃO adquirida", capacity_mock.call_count == 0)
    ok &= _ok("msg ocasional", text == HUMAN_MODE_WAIT_MESSAGE)
    exit_human_mode(ch, uid)
    return ok


async def main() -> int:
    print("=" * 60)
    print("VALIDAÇÃO B-2 — Modo humano (handoff)")
    print("=" * 60)

    results: list[bool] = []
    async with AsyncSessionLocal() as session:
        row = await session.execute(select(Tabulacao).where(Tabulacao.codigo == "NEG:ESCALADO"))
        if row.scalar_one_or_none() is None:
            from app.core.seed import seed_default_tabulacoes

            await seed_default_tabulacoes(session)
            await session.commit()

        results.append(await test_escalation_enters_human_mode(session))
        results.append(await test_short_circuit_no_llm(session))
        results.append(await test_manual_reactivate(session))
        results.append(await test_ttl_expiry(session))
        results.append(await test_normal_contact_unaffected(session))
        results.append(await test_process_receptive_skips_queue(session))

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed}/{total} cenários OK")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
