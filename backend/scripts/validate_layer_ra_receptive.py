"""
Validação R-A — fila receptiva + capacidade global ponderada.

Uso (stack Docker):
  docker exec -e MAX_WEIGHTED_CAPACITY=2 autonomous-agent-worker \\
    python /workspace/backend/scripts/validate_layer_ra_receptive.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ajuste de capacidade antes de importar settings
os.environ["MAX_WEIGHTED_CAPACITY"] = os.environ.get("MAX_WEIGHTED_CAPACITY", "2")

from app.core.activation_defaults import MESSAGING_CHANNELS
from app.core.config import settings

settings.max_weighted_capacity = int(os.environ["MAX_WEIGHTED_CAPACITY"])
from app.services.capacity_service import (
    current_global_usage,
    release_global,
    try_acquire_global,
)
from app.services.receptive_queue import (
    dequeue_next,
    enqueue_receptive,
    list_queue_members,
    queue_size,
)
from app.services.receptive_window import is_receptive_window_open
from worker.tasks.inbound_handler import _process_inbound_message
from worker.tasks.receptive_queue import _process_receptive_queue_async


def _redis_flush_receptive_keys() -> None:
    import redis as sync_redis

    client = sync_redis.from_url(settings.redis_url, decode_responses=True)
    for key in client.scan_iter("receptive_queue:*"):
        client.delete(key)
    for key in client.scan_iter("queue_payload:*"):
        client.delete(key)
    for key in client.scan_iter("global_capacity*"):
        client.delete(key)
    for key in client.scan_iter("contact_capacity:*"):
        client.delete(key)
    for key in client.scan_iter("slots_set:*"):
        client.delete(key)
    for key in client.scan_iter("slot_holder:*"):
        client.delete(key)
    client.delete("global_capacity_usage", "global_capacity_holders")


async def test_capacity_and_fifo() -> tuple[bool, str]:
    _redis_flush_receptive_keys()
    agent_id = str(uuid.uuid4())
    base_score = time.time()
    for i, phone in enumerate(
        (
            "whatsapp:+5511888000001",
            "whatsapp:+5511888000002",
            "whatsapp:+5511888000003",
        )
    ):
        enqueue_receptive(
            "whatsapp",
            phone,
            message=f"msg-{i}",
            agent_id=agent_id,
            enqueued_at=base_score + i,
        )

    members = list_queue_members("whatsapp", 10)
    if len(members) != 3:
        return False, f"FIFO enqueue: esperado 3 na fila, got {len(members)}"

    # Simula capacidade cheia
    t1 = try_acquire_global(1)
    t2 = try_acquire_global(1)
    t3 = try_acquire_global(1)
    if t3 is not None:
        return False, "capacidade global: 3º acquire deveria falhar com max=2"
    usage = current_global_usage()
    if usage != 2:
        return False, f"global_usage esperado 2, got {usage}"

    release_global(t1, 1)
    first = dequeue_next("whatsapp")
    if first is None:
        return False, "dequeue_next retornou None"
    if first.user_id != "whatsapp:+5511888000001":
        return False, f"FIFO: primeiro deveria ser .0001, got {first.user_id}"

    return True, f"FIFO ok primeiro={first.user_id} usage_after_release={current_global_usage()}"


async def test_inbound_three_contacts() -> tuple[bool, str]:
    _redis_flush_receptive_keys()
    phones = [
        "whatsapp:+5511777000001",
        "whatsapp:+5511777000002",
        "whatsapp:+5511777000003",
    ]
    results = []
    for p in phones:
        text = await _process_inbound_message("whatsapp", p, f"RA test {p}")
        results.append(text)

    usage = current_global_usage()
    qsize = queue_size("whatsapp")
    wait_count = sum(1 for t in results if "fila" in t.lower())
    if usage > 2:
        return False, f"usage {usage} > 2"
    if qsize < 1:
        return False, f"esperado >=1 na fila, qsize={qsize}"
    if wait_count < 1:
        return False, f"esperado msg de espera, results={results}"
    return True, f"usage={usage} queue={qsize} wait_msgs={wait_count}"


async def test_window_247() -> tuple[bool, str]:
    params = {"receptivo_horario_inicio": "00:00", "receptivo_horario_fim": "23:59"}
    if not is_receptive_window_open(params):
        return False, "24/7 default deveria estar aberto"
    narrow = {"receptivo_horario_inicio": "03:00", "receptivo_horario_fim": "04:00"}
    # Fora de 03-04 na maioria do dia
    open_now = is_receptive_window_open(narrow)
    return True, f"24/7=True narrow_now={open_now} (narrow esperado False fora 03-04)"


def test_atomic_acquire() -> tuple[bool, str]:
    _redis_flush_receptive_keys()
    settings.max_weighted_capacity = int(os.environ["MAX_WEIGHTED_CAPACITY"])

    def _try() -> bool:
        return try_acquire_global(1, max_capacity=2) is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_try) for _ in range(8)]
        wins = sum(1 for f in as_completed(futures) if f.result())

    usage = current_global_usage()
    if wins != 2 or usage != 2:
        return False, f"atomic: wins={wins} usage={usage} (esperado 2/2)"
    return True, f"atomic ok wins={wins} usage={usage}"


async def test_queue_processor_after_release() -> tuple[bool, str]:
    _redis_flush_receptive_keys()
    await test_inbound_three_contacts()
    if queue_size("whatsapp") < 1:
        return False, "sem itens na fila antes do processador"

    from app.services.capacity_service import release_contact_capacity

    released = release_contact_capacity("whatsapp", "whatsapp:+5511777000001")
    if not released:
        return False, "não liberou capacidade do contato .0001 para testar fila"

    stats = await _process_receptive_queue_async()
    if stats.get("served", 0) < 1:
        return False, f"processador não serviu após release: {stats}"
    return True, str(stats)


async def test_outside_window_no_queue() -> tuple[bool, str]:
    from app.services.receptive_window import outside_receptive_window_message

    narrow = {"receptivo_horario_inicio": "03:00", "receptivo_horario_fim": "04:00"}
    if is_receptive_window_open(narrow):
        return True, "janela estreita aberta agora (03-04); skip teste fora-de-horário"
    msg = outside_receptive_window_message(narrow)
    if "03:00" not in msg or "04:00" not in msg:
        return False, f"mensagem fora-de-horário inesperada: {msg}"
    return True, f"fora-de-horário: {msg[:60]}..."


async def test_active_skips_queue() -> tuple[bool, str]:
    from app.services.receptive_queue import is_in_queue

    _redis_flush_receptive_keys()
    phone = "whatsapp:+5511999001001"
    text = await _process_inbound_message("whatsapp", phone, "ACTIVE não deve enfileirar")
    if is_in_queue("whatsapp", phone):
        return False, "contato ACTIVE entrou na fila receptiva"
    if "fila" in text.lower():
        return False, f"resposta parece fila: {text[:80]}"
    return True, "ACTIVE atendido sem fila"


async def test_queue_idempotency() -> tuple[bool, str]:
    _redis_flush_receptive_keys()
    agent_id = str(uuid.uuid4())
    user = "whatsapp:+5511666555001"
    enqueue_receptive("whatsapp", user, message="m1", agent_id=agent_id, enqueued_at=100.0)
    enqueue_receptive("whatsapp", user, message="m2", agent_id=agent_id, enqueued_at=200.0)
    if queue_size("whatsapp") != 1:
        return False, f"tamanho fila {queue_size('whatsapp')} != 1"
    members = list_queue_members("whatsapp", 5)
    score = members[0][1] if members else -1
    if score != 100.0:
        return False, f"score deveria preservar 100.0, got {score}"
    return True, "idempotência ok (1 entrada, score antigo)"


async def main() -> int:
    from app.core.database import engine

    settings.max_weighted_capacity = int(os.environ["MAX_WEIGHTED_CAPACITY"])
    _redis_flush_receptive_keys()

    tests: list[tuple[str, object]] = [
        ("Atomicidade global Lua", asyncio.to_thread(test_atomic_acquire)),
        ("Janela 24/7 default", test_window_247()),
        ("FIFO dequeue", test_capacity_and_fifo()),
        ("Idempotência na fila", test_queue_idempotency()),
        ("3 inbound → 2 capacidade + fila", test_inbound_three_contacts()),
        ("Beat processa fila após release", test_queue_processor_after_release()),
        ("ACTIVE não enfileira", test_active_skips_queue()),
        ("Fora-de-horário (janela estreita)", test_outside_window_no_queue()),
    ]

    ok_all = True
    for name, coro in tests:
        if asyncio.iscoroutine(coro):
            ok, detail = await coro
        else:
            ok, detail = coro
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        ok_all = ok_all and ok

    await engine.dispose()
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
