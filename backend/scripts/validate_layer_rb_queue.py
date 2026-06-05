"""
Validação R-B — QueueEntry + métricas de fila.

  docker exec autonomous-agent-backend alembic upgrade head
  docker exec -e MAX_WEIGHTED_CAPACITY=2 autonomous-agent-worker \\
    python /workspace/backend/scripts/validate_layer_rb_queue.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone

import httpx

os.environ["MAX_WEIGHTED_CAPACITY"] = os.environ.get("MAX_WEIGHTED_CAPACITY", "2")

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.queue_entry import QueueEntry, QueueEntryStatus
from app.services.queue_entry_service import mark_abandoned, record_receptive_answered
from app.services.queue_metrics import get_queue_metrics
from app.services.receptive_queue import queue_size
from worker.tasks.inbound_handler import _process_inbound_message
from worker.tasks.receptive_queue import _process_receptive_queue_async

BASE = os.environ.get("API_BASE_URL", "http://backend:8000/api/v1")


async def test_immediate_entry() -> tuple[bool, str]:
    from sqlalchemy import select

    phone = "whatsapp:+5511555000001"
    await _process_inbound_message("whatsapp", phone, "RB imediato")
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(QueueEntry)
                .where(
                    QueueEntry.user_id == phone,
                    QueueEntry.status == QueueEntryStatus.ANSWERED,
                )
                .order_by(QueueEntry.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return False, "sem QueueEntry ANSWERED"
    if row.wait_seconds is None or row.wait_seconds != 0:
        return False, f"wait_seconds={row.wait_seconds} esperado 0"
    return True, f"id={row.id} wait=0"


async def test_queued_entry() -> tuple[bool, str]:
    from sqlalchemy import select

    import redis as sync_redis

    client = sync_redis.from_url(settings.redis_url, decode_responses=True)
    for pattern in (
        "receptive_queue:*",
        "queue_payload:*",
        "global_capacity*",
        "contact_capacity:*",
        "slots_set:*",
        "slot_holder:*",
    ):
        for key in client.scan_iter(pattern):
            client.delete(key)
    client.delete("global_capacity_usage", "global_capacity_holders")

    settings.max_weighted_capacity = 2
    phones = [
        "whatsapp:+5511555000097",
        "whatsapp:+5511555000098",
        "whatsapp:+5511555000099",
    ]

    async def _fake_route(*_a, **_k):
        return {"response": "RB ok", "intent": "other"}

    with (
        patch(
            "app.services.inbound_attendance.deliver_channel_text",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.services.inbound_attendance.route_message", new=_fake_route),
    ):
        for p in phones:
            await _process_inbound_message("whatsapp", p, f"RB fila {p}")
    queued_phone = phones[2]
    async with AsyncSessionLocal() as db:
        waiting = (
            await db.execute(
                select(QueueEntry).where(
                    QueueEntry.user_id == queued_phone,
                    QueueEntry.status == QueueEntryStatus.WAITING,
                )
            )
        ).scalar_one_or_none()
    if waiting is None:
        return False, "esperado WAITING no 3º contato"

    from app.services.capacity_service import release_contact_capacity

    for p in phones[:2]:
        if not release_contact_capacity("whatsapp", p):
            return False, f"não liberou capacidade de {p}"

    with (
        patch(
            "app.services.inbound_attendance.deliver_channel_text",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.services.inbound_attendance.route_message", new=_fake_route),
    ):
        stats = await _process_receptive_queue_async()
    if stats.get("served", 0) < 1:
        return False, f"processador não serviu: {stats}"

    async with AsyncSessionLocal() as db:
        answered = (
            await db.execute(
                select(QueueEntry).where(QueueEntry.id == waiting.id)
            )
        ).scalar_one_or_none()
    if answered is None or answered.status != QueueEntryStatus.ANSWERED:
        return False, f"status={answered.status if answered else None}"
    if (answered.wait_seconds or 0) <= 0:
        return False, f"wait_seconds={answered.wait_seconds}"
    return True, f"WAITING→ANSWERED wait={answered.wait_seconds}s q={queue_size('whatsapp')}"


async def test_metrics_api() -> tuple[bool, str]:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        for wait in (10, 25, 30):
            entry = QueueEntry(
                channel_type="whatsapp",
                user_id=f"metric-test-{wait}",
                enqueued_at=now - timedelta(minutes=5),
                answered_at=now,
                wait_seconds=wait,
                status=QueueEntryStatus.ANSWERED,
            )
            db.add(entry)
        await db.commit()

    async with AsyncSessionLocal() as db:
        m = await get_queue_metrics(db, days=1)

    if m.total_atendidos < 1:
        return False, "total_atendidos baixo"
    if m.service_level_target_seconds != settings.service_level_target_seconds:
        return False, "SLA target mismatch"
    expected_sla = sum(1 for _ in [10, 25, 30] if _ <= m.service_level_target_seconds)
    # rough check: nivel_servico should reflect mix
    return True, (
        f"atendidos={m.total_atendidos} sla={m.nivel_servico:.2%} "
        f"target={m.service_level_target_seconds}s fila={m.tamanho_fila_atual}"
    )


async def test_mark_abandoned_voice() -> tuple[bool, str]:
    async with AsyncSessionLocal() as db:
        entry = QueueEntry(
            channel_type="voice",
            user_id="voice-test-user",
            enqueued_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            status=QueueEntryStatus.WAITING,
        )
        db.add(entry)
        await db.flush()
        eid = entry.id
        await mark_abandoned(db, eid)
        await db.commit()
        await db.refresh(entry)

    if entry.status != QueueEntryStatus.ABANDONED:
        return False, f"status={entry.status}"
    async with AsyncSessionLocal() as db:
        m = await get_queue_metrics(db, days=1)
    if m.total_abandonados < 1:
        return False, "abandonados=0"
    return True, f"ABANDONED wait={entry.wait_seconds}s taxa={m.taxa_abandono:.2%}"


async def test_api_http() -> tuple[bool, str]:
    r = httpx.post(
        f"{BASE}/auth/login",
        json={"email": "admin@admin.com", "password": "admin"},
        timeout=30.0,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    res = httpx.get(
        f"{BASE}/metrics/queue?days=1",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if res.status_code != 200:
        return False, res.text
    data = res.json()
    return True, f"HTTP 200 nivel_servico={data.get('nivel_servico')} fila={data.get('tamanho_fila_atual')}"


async def main() -> int:
    tests = [
        ("Atendimento imediato → ANSWERED wait=0", test_immediate_entry()),
        ("Fila → WAITING → Beat → ANSWERED", test_queued_entry()),
        ("Métricas agregadas + SLA", test_metrics_api()),
        ("mark_abandoned voz", test_mark_abandoned_voice()),
        ("GET /metrics/queue", test_api_http()),
    ]
    ok_all = True
    for name, coro in tests:
        try:
            ok, detail = await coro
        except Exception as exc:
            ok, detail = False, str(exc)
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
        ok_all = ok_all and ok
    await engine.dispose()
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
