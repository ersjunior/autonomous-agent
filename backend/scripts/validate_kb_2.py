#!/usr/bin/env python3
"""Validação KB-2 — recuperação semântica + injeção no grafo."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select

from agents.memory.long_term import LongTermMemory
from agents.orchestrator.router import route_message
from agents.tools.knowledge_base import retrieve_kb_chunks
from agents.workers.intent_agent import IntentResult
from agents.workers.response_agent import build_response_messages, format_kb_context_block, format_rag_context_block
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent import Agent, AgentMode
from app.models.knowledge import KBDocument, KBDocumentStatus, KBSourceType
from app.models.user import User
from app.services.kb_storage import save_manual_text
from worker.tasks.conversation_routing import agent_routing_metadata
from worker.tasks.kb_ingestion import _process_kb_document_async


KB_TEST_FACTS = (
    "O horário de funcionamento é de segunda a sexta, das 8h às 18h. "
    "O frete para a região Sul é grátis acima de R$ 200."
)
PRIVATE_SECRET = "Código interno exclusivo do usuário A: ALPHA-SECRET-9911."


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    status = "OK" if cond else "FALHA"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond


async def _admin_user(session) -> User:
    return (
        await session.execute(select(User).where(User.email == "admin@admin.com"))
    ).scalar_one()


async def _ingest_manual(
    session,
    user_id: uuid.UUID,
    title: str,
    content: str,
    *,
    is_system: bool = False,
) -> KBDocument:
    doc_id = uuid.uuid4()
    dest = save_manual_text(user_id, doc_id, content)
    doc = KBDocument(
        id=doc_id,
        user_id=user_id,
        title=title,
        source_type=KBSourceType.MANUAL.value,
        filename="manual.txt",
        mime_type="text/plain",
        file_path=str(dest),
        status=KBDocumentStatus.PROCESSING.value,
        is_system=is_system,
    )
    session.add(doc)
    await session.commit()
    await _process_kb_document_async(doc_id)
    session.expire_all()
    refreshed = await session.get(KBDocument, doc_id)
    if refreshed is None or refreshed.status != KBDocumentStatus.READY.value:
        raise RuntimeError(f"Ingestão falhou: {refreshed.status if refreshed else 'missing'}")
    return refreshed


async def _route_with_intent(
    message: str,
    *,
    owner_user_id: str | None,
    agent_mode: str = "RECEPTIVE",
    user_id: str | None = None,
) -> dict:
    async def fake_identify(msg: str, history: list) -> IntentResult:
        return IntentResult(intent="question", confidence=0.9, entities={})

    agent_ctx = {
        "agent_id": "kb2-test",
        "agent_name": "KB2 Test Agent",
        "agent_mode": agent_mode,
        "agent_personality": "Agente de validação KB-2.",
        "owner_user_id": owner_user_id,
    }

    contact = user_id or f"KB2TEST_{uuid.uuid4().hex[:8]}"
    with patch("agents.orchestrator.graph.run_identify_intent", new=AsyncMock(side_effect=fake_identify)):
        return await route_message(message, "telegram", contact, agent_context=agent_ctx)


def _print_chunks(chunks: list[dict], label: str) -> None:
    print(f"    {label}: {len(chunks)} chunk(s)")
    for item in chunks:
        print(
            f"      sim={item.get('similarity', 0):.3f} "
            f"title={item.get('document_title')!r} "
            f"is_system={item.get('document_is_system')} | "
            f"{(item.get('content') or '')[:90]}"
        )


async def test_seed_kb(session, admin_id: uuid.UUID) -> KBDocument:
    print("\n=== Seed documento KB com fatos verificáveis ===")
    doc = await _ingest_manual(
        session,
        admin_id,
        "Políticas KB-2",
        KB_TEST_FACTS,
        is_system=True,
    )
    _ok("documento READY", doc.chunk_count > 0, f"chunks={doc.chunk_count}")
    return doc


async def test_retriever_horario(admin_id: uuid.UUID) -> bool:
    print("\n=== Retriever: horário ===")
    chunks = await retrieve_kb_chunks(str(admin_id), "qual o horário de vocês?")
    _print_chunks(chunks, "kb_chunks")
    hit = any("8h" in (c.get("content") or "") and "18h" in (c.get("content") or "") for c in chunks)
    return _ok("chunk com 8h-18h", hit)


async def test_retriever_frete(admin_id: uuid.UUID) -> bool:
    print("\n=== Retriever: frete Sul ===")
    chunks = await retrieve_kb_chunks(str(admin_id), "tem frete grátis para o sul?")
    _print_chunks(chunks, "kb_chunks")
    hit = any("R$ 200" in (c.get("content") or "") or "200" in (c.get("content") or "") for c in chunks)
    return _ok("chunk com frete R$200 Sul", hit)


async def test_retriever_irrelevant(admin_id: uuid.UUID) -> bool:
    print("\n=== Retriever: pergunta sem relação (threshold) ===")
    chunks = await retrieve_kb_chunks(str(admin_id), "como você está hoje?")
    _print_chunks(chunks, "kb_chunks")
    return _ok(
        "sem injeção irrelevante (threshold filtra)",
        len(chunks) == 0,
        f"{len(chunks)} chunk(s) acima de {settings.kb_similarity_threshold}",
    )


async def test_scope_isolation(session, admin_id: uuid.UUID) -> bool:
    print("\n=== Escopo: privado A + institucional ===")
    private_doc = await _ingest_manual(
        session,
        admin_id,
        "Segredo A",
        PRIVATE_SECRET,
        is_system=False,
    )

    owner_a = str(admin_id)
    other_owner = str(uuid.uuid4())

    chunks_a = await retrieve_kb_chunks(owner_a, "código interno exclusivo")
    chunks_other_private = await retrieve_kb_chunks(other_owner, "código interno exclusivo")
    chunks_other_inst = await retrieve_kb_chunks(other_owner, "qual o horário de funcionamento?")

    a_sees_private = any(PRIVATE_SECRET[:20] in (c.get("content") or "") for c in chunks_a)
    other_sees_private = any(
        PRIVATE_SECRET[:20] in (c.get("content") or "") for c in chunks_other_private
    )
    other_sees_institutional = any(
        c.get("document_is_system") and "8h" in (c.get("content") or "")
        for c in chunks_other_inst
    )

    await session.delete(private_doc)
    await session.commit()

    return (
        _ok("dono A vê chunk privado", a_sees_private)
        and _ok("outro dono NÃO vê privado de A", not other_sees_private)
        and _ok("outro dono ainda vê is_system", other_sees_institutional)
    )


async def test_inbound_response_horario(admin_id: uuid.UUID) -> bool:
    print("\n=== Inbound receptivo: horário na resposta ===")
    result = await _route_with_intent(
        "qual o horário de vocês?",
        owner_user_id=str(admin_id),
        agent_mode="RECEPTIVE",
    )
    chunks = result.get("kb_chunks") or []
    _print_chunks(chunks, "state.kb_chunks")
    response = (result.get("response") or "").lower()
    print(f"    Resposta: {result.get('response', '')[:280]}")
    uses_kb = ("8" in response and "18" in response) or "8h" in response
    return _ok("resposta usa horário da KB (8h-18h)", uses_kb and len(chunks) > 0)


async def test_inbound_response_frete(admin_id: uuid.UUID) -> bool:
    print("\n=== Inbound receptivo: frete na resposta ===")
    result = await _route_with_intent(
        "tem frete grátis para a região sul?",
        owner_user_id=str(admin_id),
        agent_mode="RECEPTIVE",
    )
    chunks = result.get("kb_chunks") or []
    _print_chunks(chunks, "state.kb_chunks")
    response = (result.get("response") or "").lower()
    print(f"    Resposta: {result.get('response', '')[:280]}")
    uses_kb = "200" in response or "r$" in response or "sul" in response
    return _ok("resposta menciona frete/região Sul", uses_kb and len(chunks) > 0)


async def test_active_mode_uses_kb(session, admin_id: uuid.UUID) -> bool:
    print("\n=== ACTIVE também consulta KB ===")
    agent = (
        await session.execute(
            select(Agent).where(Agent.mode == AgentMode.ACTIVE, Agent.is_system.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    ctx = agent_routing_metadata(agent) if agent else {"owner_user_id": str(admin_id), "agent_mode": "ACTIVE"}
    ctx["agent_mode"] = "ACTIVE"

    async def fake_identify(msg: str, history: list) -> IntentResult:
        return IntentResult(intent="question", confidence=0.9, entities={})

    with patch("agents.orchestrator.graph.run_identify_intent", new=AsyncMock(side_effect=fake_identify)):
        result = await route_message(
            "qual o horário de funcionamento?",
            "whatsapp",
            f"KB2ACTIVE_{uuid.uuid4().hex[:6]}",
            agent_context=ctx,
        )
    chunks = result.get("kb_chunks") or []
    _print_chunks(chunks, "state.kb_chunks")
    return _ok("ACTIVE recuperou chunks KB", len(chunks) > 0)


async def test_dual_rag_blocks(admin_id: uuid.UUID) -> bool:
    print("\n=== Memória + KB coexistem no prompt ===")
    memory = LongTermMemory()
    contact = f"KB2MEM_{uuid.uuid4().hex[:6]}"
    await memory.save_interaction(
        contact,
        "meu pedido 1234",
        "Seu pedido 1234 foi enviado ontem.",
        "question",
    )

    kb_chunks = await retrieve_kb_chunks(str(admin_id), "qual o horário?")
    rag_memories = await memory.retrieve_similar_memories(contact, "como está meu pedido?")

    kb_block = format_kb_context_block(kb_chunks)
    mem_block = format_rag_context_block(rag_memories)
    messages = build_response_messages(
        "qual o horário e meu pedido?",
        "question",
        {},
        [],
        "telegram",
        rag_memories=rag_memories,
        kb_chunks=kb_chunks,
        agent_mode="RECEPTIVE",
    )
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    kb_idx = next((i for i, c in enumerate(system_contents) if "Base de conhecimento" in c), -1)
    mem_idx = next((i for i, c in enumerate(system_contents) if "Conversas anteriores relevantes" in c), -1)

    return (
        _ok("bloco KB montado", kb_block is not None)
        and _ok("bloco memória montado", mem_block is not None)
        and _ok("KB antes da memória no prompt", kb_idx >= 0 and mem_idx >= 0 and kb_idx < mem_idx)
    )


async def test_escalate_skips_rag(admin_id: uuid.UUID) -> bool:
    print("\n=== Escalonamento sem RAG (mantido) ===")

    async def fake_identify(msg: str, history: list) -> IntentResult:
        return IntentResult(intent="escalate", confidence=0.95, entities={})

    with patch("agents.orchestrator.graph.run_identify_intent", new=AsyncMock(side_effect=fake_identify)):
        result = await route_message(
            "quero falar com humano",
            "telegram",
            f"KB2ESC_{uuid.uuid4().hex[:6]}",
            agent_context={"owner_user_id": str(admin_id), "agent_mode": "RECEPTIVE"},
        )
    no_kb = not result.get("kb_chunks")
    escalated = bool(result.get("should_escalate"))
    return _ok("escalate sem kb_chunks", no_kb) and _ok("should_escalate=True", escalated)


async def main() -> int:
    print("Validação KB-2 — recuperação + injeção no grafo")
    print(
        f"  kb_top_k={settings.resolved_kb_top_k()} "
        f"kb_threshold={settings.kb_similarity_threshold}"
    )
    results: list[bool] = []

    async with AsyncSessionLocal() as session:
        admin_id = (await _admin_user(session)).id
        await test_seed_kb(session, admin_id)
        results.append(await test_retriever_horario(admin_id))
        results.append(await test_retriever_frete(admin_id))
        results.append(await test_retriever_irrelevant(admin_id))
        results.append(await test_scope_isolation(session, admin_id))
        results.append(await test_inbound_response_horario(admin_id))
        results.append(await test_inbound_response_frete(admin_id))
        results.append(await test_active_mode_uses_kb(session, admin_id))
        results.append(await test_dual_rag_blocks(admin_id))
        results.append(await test_escalate_skips_rag(admin_id))

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 50}")
    print(f"Resultado: {passed}/{total} cenários OK")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
