#!/usr/bin/env python3
"""Validação B-1 — comportamento receptivo, escalonamento inteligente, NEG:ESCALADO."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from agents.orchestrator.graph import resolve_should_escalate
from agents.workers.intent_agent import IntentResult
from agents.workers.response_agent import RECEPTIVE_BEHAVIOR_PROMPT, build_response_messages
from app.core.database import AsyncSessionLocal
from app.core.seed import seed_default_tabulacoes
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.models.user import User
from app.services.tabulacao_assignment import maybe_apply_tabulacao_on_transition
from worker.tasks.conversation_routing import agent_routing_metadata
from worker.tasks.lead_tracking import track_inbound_lead_interaction


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    status = "OK" if cond else "FALHA"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond


def test_resolve_should_escalate() -> bool:
    print("\n=== Escalonamento — resolve_should_escalate (unitário) ===")
    ok = True
    ok &= _ok("intent escalate", resolve_should_escalate("escalate", 0.99, "low"))
    ok &= _ok("baixa confiança", resolve_should_escalate("question", 0.3, "low"))
    ok &= _ok(
        "complaint grave",
        resolve_should_escalate("complaint", 0.9, "high"),
    )
    ok &= _ok(
        "complaint leve NÃO escala",
        not resolve_should_escalate("complaint", 0.9, "low"),
    )
    ok &= _ok(
        "question normal NÃO escala",
        not resolve_should_escalate("question", 0.85, "low"),
    )
    return ok


def test_receptive_prompt_injection() -> bool:
    print("\n=== Bloco RECEPTIVE no prompt (unitário) ===")
    receptive_msgs = build_response_messages(
        "Qual o horário?",
        "question",
        {},
        [],
        "telegram",
        agent_mode="RECEPTIVE",
        agent_personality="Agente receptivo de teste",
    )
    active_msgs = build_response_messages(
        "Qual o horário?",
        "question",
        {},
        [],
        "telegram",
        agent_mode="ACTIVE",
        agent_personality="Agente ativo de teste",
    )
    rec_contents = [m["content"] for m in receptive_msgs if m["role"] == "system"]
    act_contents = [m["content"] for m in active_msgs if m["role"] == "system"]

    has_receptive = any(RECEPTIVE_BEHAVIOR_PROMPT in c for c in rec_contents)
    active_has_receptive = any(RECEPTIVE_BEHAVIOR_PROMPT in c for c in act_contents)

    print("\n--- System messages RECEPTIVE ---")
    for i, c in enumerate(rec_contents):
        print(f"  [{i}] {c[:120]}{'...' if len(c) > 120 else ''}")

    ok = True
    ok &= _ok("RECEPTIVE inclui bloco operacional", has_receptive)
    ok &= _ok("ACTIVE não inclui bloco RECEPTIVE", not active_has_receptive)
    return ok


async def _ensure_escalado_seed(session) -> None:
    row = await session.execute(select(Tabulacao).where(Tabulacao.codigo == "NEG:ESCALADO"))
    if row.scalar_one_or_none() is None:
        await seed_default_tabulacoes(session)
        await session.commit()


async def _fixture_lead(session) -> tuple[Lead, str]:
    user = (
        await session.execute(select(User).where(User.email == "admin@admin.com"))
    ).scalar_one()
    campaign = (
        await session.execute(select(Campaign).where(Campaign.user_id == user.id).limit(1))
    ).scalar_one_or_none()
    if campaign is None:
        raise RuntimeError("Nenhuma campanha para testes B-1")

    lead_base = (
        await session.execute(
            select(LeadBase).where(LeadBase.campaign_id == campaign.id).limit(1)
        )
    ).scalar_one_or_none()
    if lead_base is None:
        raise RuntimeError("Nenhuma lead_base para testes B-1")

    lead = (
        await session.execute(
            select(Lead).where(Lead.lead_base_id == lead_base.id).limit(1)
        )
    ).scalar_one_or_none()
    if lead is None:
        lead = Lead(
            user_id=user.id,
            lead_base_id=lead_base.id,
            id_cliente=f"B1-{uuid.uuid4().hex[:8]}",
            nome_cliente="Lead B1",
            telefone_1="5511999887766",
        )
        session.add(lead)
        await session.flush()

    channel = "whatsapp"
    existing = (
        await session.execute(
            select(LeadInteraction).where(
                LeadInteraction.lead_id == lead.id,
                LeadInteraction.channel_type == channel,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.status = "em_andamento"
        existing.tabulacao_id = None
        existing.tabulacao_origem = None
        existing.tabulacao_aplicada_em = None
    else:
        session.add(
            LeadInteraction(
                lead_id=lead.id,
                campaign_id=campaign.id,
                channel_type=channel,
                status="em_andamento",
                tentativas=1,
                data_acionamento=datetime.now(timezone.utc),
            )
        )
    await session.flush()
    return lead, lead.telefone_1 or "5511999887766"


async def test_escalation_tabulation(session) -> bool:
    print("\n=== Tabulação NEG:ESCALADO no tracking ===")
    await _ensure_escalado_seed(session)
    lead, phone = await _fixture_lead(session)

    rec = await track_inbound_lead_interaction(
        session,
        "whatsapp",
        phone,
        "quero falar com um humano",
        "escalate",
        escalated=True,
    )
    await session.commit()
    if rec:
        await session.refresh(rec, ["tabulacao"])

    codigo = rec.tabulacao.codigo if rec and rec.tabulacao else None
    return _ok(
        "escalated=True → NEG:ESCALADO origem ESCALATION",
        rec is not None
        and codigo == "NEG:ESCALADO"
        and rec.tabulacao_origem == "ESCALATION",
        f"codigo={codigo} origem={rec.tabulacao_origem if rec else None} status={rec.status if rec else None}",
    )


async def _get_receptive_agent(session) -> Agent | None:
    return (
        await session.execute(
            select(Agent).where(Agent.mode == AgentMode.RECEPTIVE).limit(1)
        )
    ).scalar_one_or_none()


async def _run_route_with_intent(
    message: str,
    intent: str,
    confidence: float = 0.92,
    complaint_severity: str = "low",
    agent_mode: str = "RECEPTIVE",
) -> dict:
    from agents.orchestrator.router import route_message

    async def fake_identify(msg: str, history: list) -> IntentResult:
        return IntentResult(
            intent=intent,
            confidence=confidence,
            entities={},
            complaint_severity=complaint_severity,
        )

    agent_ctx = {
        "agent_id": "test",
        "agent_name": "Agente_Receptivo",
        "agent_mode": agent_mode,
        "agent_personality": "Agente receptivo para validação B-1.",
    }

    with patch(
        "agents.orchestrator.graph.run_identify_intent",
        new=AsyncMock(side_effect=fake_identify),
    ):
        with patch(
            "agents.orchestrator.graph._long_term_memory.retrieve_similar_memories",
            new=AsyncMock(return_value=[{"message": "horário", "response": "9h-18h", "similarity": 0.88}]),
        ):
            return await route_message(
                message,
                "telegram",
                f"B1TEST_{uuid.uuid4().hex[:8]}",
                agent_context=agent_ctx,
            )


async def test_route_escalate_explicit(session) -> bool:
    print("\n=== Rota: pedido explícito de humano ===")
    lead, phone = await _fixture_lead(session)
    lead.telefone_1 = phone
    await session.commit()

    from agents.orchestrator.router import route_message
    from worker.tasks.conversation_routing import agent_routing_metadata

    agent = await _get_receptive_agent(session)
    ctx = agent_routing_metadata(agent) if agent else {"agent_mode": "RECEPTIVE"}

    async def fake_identify(msg: str, history: list) -> IntentResult:
        return IntentResult(intent="escalate", confidence=0.95, entities={})

    with patch("agents.orchestrator.graph.run_identify_intent", new=AsyncMock(side_effect=fake_identify)):
        result = await route_message(
            "quero falar com um humano",
            "whatsapp",
            phone,
            agent_context=ctx,
        )

    rec = await track_inbound_lead_interaction(
        session,
        "whatsapp",
        phone,
        "quero falar com um humano",
        result.get("intent", "escalate"),
        escalated=bool(result.get("should_escalate")),
    )
    await session.commit()
    if rec:
        await session.refresh(rec, ["tabulacao"])

    resp = (result.get("response") or "").lower()
    codigo = rec.tabulacao.codigo if rec and rec.tabulacao else None
    ok = True
    ok &= _ok("should_escalate=true", bool(result.get("should_escalate")))
    ok &= _ok("resposta de transferência", "humano" in resp or "atendente" in resp, resp[:120])
    ok &= _ok("NEG:ESCALADO aplicado", codigo == "NEG:ESCALADO", f"codigo={codigo}")
    return ok


async def test_route_severe_complaint(session) -> bool:
    print("\n=== Rota: reclamação grave ===")
    result = await _run_route_with_intent(
        "isso é um absurdo, vou processar vocês, péssimo serviço",
        "complaint",
        confidence=0.91,
        complaint_severity="high",
    )
    resp = (result.get("response") or "").lower()
    ok = True
    ok &= _ok("intent=complaint", result.get("intent") == "complaint")
    ok &= _ok("severity=high no state", result.get("complaint_severity") == "high")
    ok &= _ok("should_escalate=true", bool(result.get("should_escalate")))
    ok &= _ok("resposta transferência", "humano" in resp or "atendente" in resp, resp[:120])
    return ok


async def test_route_light_complaint(session) -> bool:
    print("\n=== Rota: reclamação leve (bot responde) ===")
    result = await _run_route_with_intent(
        "achei o atendimento meio devagar",
        "complaint",
        confidence=0.88,
        complaint_severity="low",
    )
    ok = True
    ok &= _ok("should_escalate=false", not result.get("should_escalate"))
    ok &= _ok("resposta gerada (não vazia)", bool((result.get("response") or "").strip()))
    ok &= _ok(
        "não é só mensagem fixa de escalate",
        "encaminhar você para um atendente humano" not in (result.get("response") or "").lower(),
    )
    return ok


async def test_receptive_qualification_and_rag(session) -> bool:
    print("\n=== Rota RECEPTIVE: dúvida + qualificação + RAG ===")
    vague = await _run_route_with_intent(
        "quero saber sobre vocês",
        "question",
        confidence=0.9,
    )
    doubt = await _run_route_with_intent(
        "qual o horário de atendimento?",
        "question",
        confidence=0.9,
    )

    from agents.workers.response_agent import build_response_messages

    msgs = build_response_messages(
        "quero saber sobre vocês",
        "question",
        {},
        [],
        "telegram",
        agent_mode="RECEPTIVE",
        rag_memories=[{"message": "horário", "response": "9h-18h", "similarity": 0.9}],
    )
    rag_in_prompt = any("memória de longo prazo" in m.get("content", "") for m in msgs)

    vague_resp = (vague.get("response") or "").lower()
    has_question = "?" in (vague.get("response") or "")
    ok = True
    ok &= _ok("RAG no prompt montado", rag_in_prompt)
    ok &= _ok("rag_memories no state", len(vague.get("rag_memories") or []) >= 1)
    ok &= _ok(
        "lead vago — resposta tenta qualificar (?) ",
        has_question or any(w in vague_resp for w in ("o que", "qual", "como", "interesse", "busca")),
        (vague.get("response") or "")[:160],
    )
    ok &= _ok(
        "dúvida — resposta não vazia",
        bool((doubt.get("response") or "").strip()),
        (doubt.get("response") or "")[:160],
    )
    return ok


async def test_active_no_receptive_block(session) -> bool:
    print("\n=== ACTIVE: sem bloco receptivo na rota ===")
    result = await _run_route_with_intent(
        "preciso de informações",
        "question",
        agent_mode="ACTIVE",
    )
    msgs = build_response_messages(
        "preciso de informações",
        "question",
        {},
        [],
        "telegram",
        agent_mode="ACTIVE",
    )
    has_block = any(RECEPTIVE_BEHAVIOR_PROMPT in m.get("content", "") for m in msgs)
    ok = True
    ok &= _ok("agent_mode ACTIVE no fluxo", not has_block)
    ok &= _ok("resposta gerada", bool((result.get("response") or "").strip()))
    return ok


async def main() -> int:
    print("=" * 60)
    print("VALIDAÇÃO B-1 — Receptivo + Escalonamento + NEG:ESCALADO")
    print("=" * 60)

    results: list[bool] = []
    results.append(test_resolve_should_escalate())
    results.append(test_receptive_prompt_injection())

    async with AsyncSessionLocal() as session:
        results.append(await test_escalation_tabulation(session))
        results.append(await test_route_escalate_explicit(session))
        results.append(await test_route_severe_complaint(session))
        results.append(await test_route_light_complaint(session))
        results.append(await test_receptive_qualification_and_rag(session))
        results.append(await test_active_no_receptive_block(session))

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed}/{total} cenários OK")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
