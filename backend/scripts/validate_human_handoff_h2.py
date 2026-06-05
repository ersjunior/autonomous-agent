#!/usr/bin/env python3
"""Validação H-2 — ciclo de finalização do handoff humano."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select

from agents.workers.intent_agent import IntentResult
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent import Agent, AgentMode
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.models.user import User
from app.services.human_handoff import (
    assume_human_mode,
    exit_human_mode,
    finalize_handoff_lead,
    get_human_mode_payload,
    is_assumed,
    is_in_human_mode,
    resolved_finalize_ttl_seconds,
    resolved_queue_ttl_seconds,
    sweep_human_handoff_timeouts,
)
from app.services.inbound_attendance import attend_inbound_message
from worker.tasks.human_handoff_sweep import _sweep_human_handoff_async


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
        raise RuntimeError("Nenhum lead para testes H-2")
    phone = lead.telefone_1 or "5511999887766"
    return lead, phone


async def test_escalation_panel_state(session) -> bool:
    print("\n=== Escalonamento → painel aguardando ===")
    lead, phone = await _fixture_lead_phone(session)
    agent = await _get_receptive_agent(session)
    if agent is None:
        return _ok("agente receptivo", False)

    ch = "whatsapp"
    exit_human_mode(ch, phone)

    with (
        patch(
            "app.services.inbound_attendance.route_message",
            new_callable=AsyncMock,
            return_value={
                "response": "Transferindo para humano.",
                "should_escalate": True,
                "intent": "escalate",
            },
        ),
        patch("app.services.inbound_attendance.deliver_channel_text", new=AsyncMock()),
        patch(
            "app.services.human_handoff.handle_escalation_handoff",
            new_callable=AsyncMock,
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

    payload = get_human_mode_payload(ch, phone)
    ok = _ok("modo humano ativo", is_in_human_mode(ch, phone))
    ok &= _ok("aguardando (não assumido)", not is_assumed(ch, phone))
    ok &= _ok("payload human_assumed_at null", payload and payload.get("human_assumed_at") is None)
    exit_human_mode(ch, phone)
    return ok


async def test_assume_extends_state(session) -> bool:
    print("\n=== Assumir → assumido + TTL estendido ===")
    lead, phone = await _fixture_lead_phone(session)
    ch = "whatsapp"
    exit_human_mode(ch, phone)

    from app.services.human_handoff import enter_human_mode

    enter_human_mode(ch, phone, intent="escalate")
    ok = assume_human_mode(ch, phone, assumed_by="operador@teste")
    ok &= _ok("assume retornou True", ok)
    ok &= _ok("is_assumed", is_assumed(ch, phone))
    payload = get_human_mode_payload(ch, phone)
    ok &= _ok("human_assumed_at preenchido", bool(payload and payload.get("human_assumed_at")))
    ok &= _ok("assumed_by", payload.get("assumed_by") == "operador@teste" if payload else False)

    from app.services.human_handoff import _get_redis, _human_mode_key

    ttl = _get_redis().ttl(_human_mode_key(ch, phone))
    ok &= _ok(
        "TTL próximo de finalize_ttl",
        ttl >= resolved_finalize_ttl_seconds() - 5,
        f"ttl={ttl} finalize={resolved_finalize_ttl_seconds()}",
    )
    exit_human_mode(ch, phone)
    return ok


async def test_finalize_with_tabulacao(session) -> bool:
    print("\n=== Finalizar NEG:SUCESSO → convertido + Redis limpo ===")
    lead, phone = await _fixture_lead_phone(session)
    ch = "whatsapp"
    exit_human_mode(ch, phone)

    from app.services.human_handoff import enter_human_mode

    enter_human_mode(ch, phone, intent="escalate")
    assume_human_mode(ch, phone, assumed_by="test")

    ok = await finalize_handoff_lead(
        session,
        channel=ch,
        user_id=phone,
        tabulacao_codigo="NEG:SUCESSO",
        origem="HANDOFF_FINALIZE",
    )
    await session.commit()
    ok &= _ok("finalize_handoff_lead", ok)
    ok &= _ok("Redis limpo", not is_in_human_mode(ch, phone))

    tab = (
        await session.execute(select(Tabulacao).where(Tabulacao.codigo == "NEG:SUCESSO"))
    ).scalar_one_or_none()

    li = (
        await session.execute(
            select(LeadInteraction)
            .where(
                LeadInteraction.lead_id == lead.id,
                LeadInteraction.channel_type == ch,
            )
            .order_by(LeadInteraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    ok &= _ok("status convertido", li and li.status == "convertido", getattr(li, "status", None))
    ok &= _ok(
        "tabulação NEG:SUCESSO",
        li and tab and li.tabulacao_id == tab.id,
        f"origem={getattr(li, 'tabulacao_origem', None)}",
    )
    ok &= _ok(
        "origem HANDOFF_FINALIZE",
        li and li.tabulacao_origem == "HANDOFF_FINALIZE",
    )
    return ok


async def test_reactivate_returns_to_bot(session) -> bool:
    print("\n=== Devolver ao bot → próxima msg atendida pelo grafo ===")
    lead, phone = await _fixture_lead_phone(session)
    agent = await _get_receptive_agent(session)
    ch = "whatsapp"
    exit_human_mode(ch, phone)

    from app.services.human_handoff import enter_human_mode

    enter_human_mode(ch, phone)
    assume_human_mode(ch, phone)
    ok = _ok("assumido antes", is_assumed(ch, phone))
    ok &= _ok("exit limpa Redis", exit_human_mode(ch, phone))
    ok &= _ok("não em modo humano", not is_in_human_mode(ch, phone))

    route_mock = AsyncMock(
        return_value={
            "response": "Bot de volta.",
            "intent": "question",
            "should_escalate": False,
        }
    )
    with patch("app.services.inbound_attendance.route_message", new=route_mock):
        with patch("app.services.inbound_attendance.deliver_channel_text", new=AsyncMock()):
            await attend_inbound_message(
                session,
                channel=ch,
                user_id=phone,
                message="ainda preciso de ajuda",
                agent=agent,
                lead=lead,
                bind_capacity=False,
            )
    ok &= _ok("grafo chamado após devolver", route_mock.await_count == 1)
    return ok


async def test_queue_timeout_returns_to_bot(session) -> bool:
    print("\n=== Timeout curto (não assumido) → devolve ao bot ===")
    ch = "telegram"
    uid = f"H2Q-{uuid.uuid4().hex[:8]}"
    exit_human_mode(ch, uid)

    from app.services.human_handoff import enter_human_mode

    original_queue = settings.human_handoff_queue_ttl_seconds
    settings.human_handoff_queue_ttl_seconds = 1
    try:
        enter_human_mode(ch, uid, intent="escalate")
        ok = _ok("ativo", is_in_human_mode(ch, uid))
        time.sleep(2)
        stats = await sweep_human_handoff_timeouts(session)
        await session.commit()
        ok &= _ok("sweep returned_to_bot", stats.get("returned_to_bot", 0) >= 1, str(stats))
        ok &= _ok("Redis limpo", not is_in_human_mode(ch, uid))
    finally:
        settings.human_handoff_queue_ttl_seconds = original_queue
        exit_human_mode(ch, uid)
    return ok


async def test_assumed_timeout_auto_finalize(session) -> bool:
    print("\n=== Timeout longo (assumido) → NEG:ABANDONO + nao_atendido ===")
    lead, phone = await _fixture_lead_phone(session)
    ch = "whatsapp"
    exit_human_mode(ch, phone)

    from app.services.human_handoff import enter_human_mode

    original_finalize = settings.human_handoff_finalize_ttl_seconds
    settings.human_handoff_finalize_ttl_seconds = 1
    try:
        enter_human_mode(ch, phone, intent="escalate")
        assume_human_mode(ch, phone, assumed_by="timeout-test")
        payload = get_human_mode_payload(ch, phone)
        if payload:
            payload["human_assumed_at"] = "2000-01-01T00:00:00+00:00"
            from app.services.human_handoff import _write_human_mode_payload

            _write_human_mode_payload(ch, phone, payload)

        stats = await sweep_human_handoff_timeouts(session)
        await session.commit()
        ok = _ok("auto_finalized", stats.get("auto_finalized", 0) >= 1, str(stats))
        ok &= _ok("Redis limpo", not is_in_human_mode(ch, phone))

        tab = (
            await session.execute(
                select(Tabulacao).where(Tabulacao.codigo == "NEG:ABANDONO")
            )
        ).scalar_one_or_none()
        li = (
            await session.execute(
                select(LeadInteraction)
                .where(
                    LeadInteraction.lead_id == lead.id,
                    LeadInteraction.channel_type == ch,
                )
                .order_by(LeadInteraction.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        ok &= _ok("status nao_atendido", li and li.status == "nao_atendido")
        ok &= _ok(
            "tabulação NEG:ABANDONO",
            li and tab and li.tabulacao_id == tab.id,
            f"origem={getattr(li, 'tabulacao_origem', None)}",
        )
    finally:
        settings.human_handoff_finalize_ttl_seconds = original_finalize
        exit_human_mode(ch, phone)
    return ok


async def test_celery_sweep_task() -> bool:
    print("\n=== Sweep async (mesmo corpo da Celery task, sem InterfaceError) ===")
    try:
        result = await _sweep_human_handoff_async()
        return _ok("sweep executou", isinstance(result, dict), str(result))
    except Exception as exc:
        if "InterfaceError" in str(exc):
            return _ok("sem InterfaceError", False, str(exc))
        return _ok("sweep executou", False, str(exc))


async def main() -> int:
    print("validate_human_handoff_h2.py — entrega H-2")
    results: list[bool] = []

    async with AsyncSessionLocal() as session:
        results.append(await test_escalation_panel_state(session))
        results.append(await test_assume_extends_state(session))
        results.append(await test_finalize_with_tabulacao(session))
        results.append(await test_reactivate_returns_to_bot(session))
        results.append(await test_queue_timeout_returns_to_bot(session))
        results.append(await test_assumed_timeout_auto_finalize(session))

    results.append(await test_celery_sweep_task())

    passed = sum(results)
    total = len(results)
    print(f"\n=== Resumo: {passed}/{total} cenários OK ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
