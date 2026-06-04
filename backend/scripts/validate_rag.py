"""Validação manual do RAG — rodar no container backend/worker."""

from __future__ import annotations

import asyncio
import json

from agents.memory.long_term import LongTermMemory
from agents.orchestrator.router import route_message
from agents.workers.response_agent import format_rag_context_block
from app.core.config import settings
from app.services.settings_sync import bootstrap_settings, ensure_settings_fresh_async


async def seed_interactions(memory: LongTermMemory, user_id: str, pairs: list[tuple[str, str]]) -> None:
    for msg, resp in pairs:
        await memory.save_interaction(user_id, msg, resp, "question")


async def main() -> None:
    await bootstrap_settings()
    await ensure_settings_fresh_async()

    memory = LongTermMemory()
    test_user = "RAGTEST"
    other_user = "OTHERUSER"

    print("=== Seed interações antigas ===")
    await seed_interactions(
        memory,
        test_user,
        [
            ("Qual o horário de funcionamento?", "Funcionamos de segunda a sexta, 9h às 18h."),
            ("Vocês entregam em domingo?", "Não entregamos aos domingos; apenas dias úteis."),
            ("Quero cancelar meu pedido", "Posso ajudar no cancelamento. Informe o número do pedido."),
        ],
    )
    await memory.save_interaction(
        other_user,
        "Segredo de outro cliente",
        "Resposta que não deve vazar",
        "other",
    )
    print("Gravadas 3 interações para RAGTEST + 1 para OTHERUSER")

    query = "Que horas vocês abrem?"
    print(f"\n=== get_similar (threshold={settings.rag_similarity_threshold}, top_k={settings.rag_top_k}) ===")
    similar = await memory.get_similar(test_user, query)
    for row in similar:
        print(
            f"  sim={row['similarity']:.4f} dist={row['distance']:.4f} "
            f"| {row['message'][:50]} -> {row['response'][:50]}"
        )

    block = format_rag_context_block(similar)
    print("\n=== Bloco RAG injetado? ===")
    print("SIM" if block else "NAO")
    if block:
        print(block[:500])

    print("\n=== Isolamento OTHERUSER na busca RAGTEST ===")
    other_hits = [r for r in similar if r["user_id"] == other_user]
    print("Vazamento:", "SIM (ERRO)" if other_hits else "NAO (OK)")

    print("\n=== Threshold alto (0.9) ===")
    old_threshold = settings.rag_similarity_threshold
    settings.rag_similarity_threshold = 0.9
    strict = await memory.get_similar(test_user, query)
    settings.rag_similarity_threshold = old_threshold
    print(f"Com threshold=0.9: {len(strict)} resultado(s)")
    loose = await memory.get_similar(test_user, query)
    settings.rag_similarity_threshold = 0.0
    all_pass = await memory.get_similar(test_user, query, limit=10)
    settings.rag_similarity_threshold = old_threshold
    print(f"Com threshold=0: {len(all_pass)} resultado(s) (até 10)")

    print("\n=== route_message (Redis deve estar limpo para RAGTEST) ===")
    result = await route_message(query, "telegram", test_user)
    print("Resposta:", (result.get("response") or "")[:300])
    print("rag_memories no state:", len(result.get("rag_memories") or []))


if __name__ == "__main__":
    asyncio.run(main())
