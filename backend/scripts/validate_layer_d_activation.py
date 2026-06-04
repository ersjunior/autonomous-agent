"""
Validação Camada D — concorrência (slots Redis + fila de prioridade).

Executar (Docker):
  docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_layer_d_activation.py

Ou localmente com REDIS_URL/DATABASE_URL do .env apontando para a stack.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import httpx

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.services.activation_slots import (
    count_active_slots,
    enqueue_priority,
    pop_priority_leads,
    priority_queue_size,
    release_slot,
    try_acquire_slot,
)
from worker.tasks.activation_scheduler import _process_active_activations_async
from worker.tasks.lead_tracking import upsert_lead_interaction

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"

WIDE_MSG = {
    "chats_simultaneos": 2,
    "campanhas_simultaneas": 1,
    "tentativas_sem_resposta": 2,
    "minutos_segunda_mensagem": 20,
    "horario_inicio": "00:00",
    "horario_fim": "23:59",
}
VOICE_PARAMS = {
    "chamadas_simultaneas": 1,
    "campanhas_simultaneas": 1,
    "tentativas_por_hora": 10,
    "horario_inicio": "00:00",
    "horario_fim": "23:59",
}
WA_TWO_SLOTS = {**WIDE_MSG, "chats_simultaneos": 2}


def login(client: httpx.Client) -> str:
    r = client.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_setup(
    client: httpx.Client,
    h: dict[str, str],
    tag: str,
    channel: str,
    lead_count: int,
    channel_params: dict,
) -> tuple[str, str, list[str]]:
    agent = client.post(
        f"{BASE}/agents/",
        headers=h,
        json={"name": f"LayerD {tag}", "mode": "ACTIVE", "description": "validação D", "config": {}},
    ).json()
    agent_id = agent["id"]
    client.put(
        f"{BASE}/agents/{agent_id}/channel-settings/{channel}",
        headers=h,
        json={"params": channel_params},
    )
    camp = client.post(
        f"{BASE}/campaigns/",
        headers=h,
        json={"name": f"Camp D {tag}", "agent_id": agent_id, "channel_types": [channel]},
    ).json()
    campaign_id = camp["id"]
    base = client.post(
        f"{BASE}/lead-bases/",
        headers=h,
        json={
            "campaign_id": campaign_id,
            "data_recebimento": date.today().isoformat(),
            "channel_types": [channel],
        },
    ).json()
    lead_ids: list[str] = []
    for i in range(1, lead_count + 1):
        phone = f"+5511988{tag[:4]}{i:03d}"
        lead = client.post(
            f"{BASE}/leads/",
            headers=h,
            json={
                "lead_base_id": base["id"],
                "nome_cliente": f"Lead D{i}",
                "telefone_1": phone,
                "aux_values": {},
            },
        ).json()
        lead_ids.append(lead["id"])
    client.post(f"{BASE}/campaigns/{campaign_id}/activations/{channel}/start", headers=h)
    return agent_id, campaign_id, lead_ids


def _cleanup(
    client: httpx.Client,
    h: dict[str, str],
    campaign_id: str,
    agent_id: str,
    channel: str,
) -> None:
    try:
        client.post(
            f"{BASE}/campaigns/{campaign_id}/activations/{channel}/stop",
            headers=h,
        )
    except Exception:
        pass
    try:
        client.delete(f"{BASE}/campaigns/{campaign_id}", headers=h)
    except Exception:
        pass
    try:
        client.delete(f"{BASE}/agents/{agent_id}", headers=h)
    except Exception:
        pass


def _record_result(
    results: list[tuple[str, bool, str]],
    name: str,
    ok: bool,
    detail: str,
) -> None:
    results.append((name, ok, detail))
    mark = "OK" if ok else "FALHA"
    print(f"  [{mark}] {name}: {detail}")


async def _run_scheduler() -> dict:
    return await _process_active_activations_async()


def _clear_agent_channel_slots(agent_id: str, channel: str) -> None:
    import redis as redis_lib

    client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    ch = channel.lower()
    aid = agent_id
    for key in client.scan_iter(f"slots_set:{aid}:{ch}"):
        for token in client.smembers(key):
            release_slot(aid, ch, token)
    client.delete(f"slots_set:{aid}:{ch}")
    client.delete(f"priority_queue:{aid}:{ch}")


async def validate_atomicity(agent_id: str, channel: str = "voice") -> tuple[bool, str]:
    _clear_agent_channel_slots(agent_id, channel)
    limit = 1
    ttl = 30

    def _try():
        return try_acquire_slot(agent_id, channel, limit, ttl)

    tokens = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_try) for _ in range(8)]
        for f in as_completed(futs):
            t = f.result()
            if t:
                tokens.append(t)

    active = count_active_slots(agent_id, channel)
    ok = len(tokens) == 1 and active == 1
    for t in tokens:
        release_slot(agent_id, channel, t)
    _clear_agent_channel_slots(agent_id, channel)
    return ok, f"tokens_obtidos={len(tokens)} active={active} (esperado 1/1)"


async def validate_ttl_phantom(agent_id: str, channel: str = "voice") -> tuple[bool, str]:
    _clear_agent_channel_slots(agent_id, channel)
    token = try_acquire_slot(agent_id, channel, 1, ttl_seconds=2)
    if not token:
        return False, "nao adquiriu slot"
    if count_active_slots(agent_id, channel) != 1:
        return False, "count != 1 apos acquire"
    time.sleep(3)
    active = count_active_slots(agent_id, channel)
    ok = active == 0
    return ok, f"active_apos_ttl={active} (esperado 0)"


async def run_validation_async(client: httpx.Client, h: dict[str, str]) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    tag = uuid.uuid4().hex[:6]

    print("\n=== D1 VOZ chamadas_simultaneas=1, 3 leads ===")
    agent_v, camp_v, leads_v = _create_setup(
        client, h, f"v{tag}", "voice", 3, VOICE_PARAMS
    )
    _clear_agent_channel_slots(agent_v, "voice")
    stats1 = await _run_scheduler()
    active1 = count_active_slots(agent_v, "voice")
    pq1 = priority_queue_size(agent_v, "voice")
    ch1 = stats1.get("by_channel", {}).get(f"{camp_v}:voice", {})
    disp1 = ch1.get("first_message", 0) + ch1.get("priority_dispatched", 0)
    ok1 = disp1 == 1 and active1 == 1 and pq1 == 2
    _record_result(
        results,
        "D1 voz 1 slot + 2 na fila",
        ok1,
        f"dispatched_campanha={disp1} slots_active={active1} priority_queue={pq1}",
    )

    print("\n=== D2 Liberar slot → próximo da PRIORITY_QUEUE ===")
    tokens = []
    import redis as redis_lib

    rclient = redis_lib.from_url(settings.redis_url, decode_responses=True)
    for m in rclient.smembers(f"slots_set:{agent_v}:voice"):
        tokens.append(m)
    if tokens:
        release_slot(agent_v, "voice", tokens[0])
    stats2 = await _run_scheduler()
    active2 = count_active_slots(agent_v, "voice")
    pq2 = priority_queue_size(agent_v, "voice")
    popped = pop_priority_leads(agent_v, "voice", 10)
    for pm in popped:
        enqueue_priority(agent_v, "voice", pm.campaign_id, pm.lead_id, followup=pm.is_followup)
    ok2 = stats2.get("priority_dispatched", 0) >= 1 and pq2 <= 1
    _record_result(
        results,
        "D2 prioridade após liberar slot",
        ok2,
        f"priority_dispatched={stats2.get('priority_dispatched')} pq={pq2} active={active2}",
    )

    _cleanup(client, h, camp_v, agent_v, "voice")

    print("\n=== D3 WHATSAPP chats_simultaneos=2, 5 leads ===")
    agent_w, camp_w, leads_w = _create_setup(
        client, h, f"w{tag}", "whatsapp", 5, WA_TWO_SLOTS
    )
    _clear_agent_channel_slots(agent_w, "whatsapp")
    stats_w1 = await _run_scheduler()
    active_w = count_active_slots(agent_w, "whatsapp")
    pq_w = priority_queue_size(agent_w, "whatsapp")
    ok_w1 = stats_w1.get("leads_enqueued", 0) == 2 and active_w == 2 and pq_w == 3
    _record_result(
        results,
        "D3 whatsapp 2 slots + 3 fila",
        ok_w1,
        f"enqueued={stats_w1.get('leads_enqueued')} active={active_w} pq={pq_w}",
    )

    import redis as redis_lib

    rclient = redis_lib.from_url(settings.redis_url, decode_responses=True)
    closed_lead = None
    for lid in leads_w:
        if rclient.exists(f"lead_slot:{lid}:whatsapp"):
            closed_lead = lid
            break

    active_before_close = count_active_slots(agent_w, "whatsapp")
    if closed_lead:
        async with AsyncSessionLocal() as db:
            await upsert_lead_interaction(
                db,
                uuid.UUID(closed_lead),
                uuid.UUID(camp_w),
                "whatsapp",
                status="nao_atendido",
                devolutiva="teste encerramento D",
            )
            await db.commit()
    active_after_close = count_active_slots(agent_w, "whatsapp")

    stats_w2 = await _run_scheduler()
    pq_after = priority_queue_size(agent_w, "whatsapp")
    ch_w2 = stats_w2.get("by_channel", {}).get(f"{camp_w}:whatsapp", {})
    disp2 = ch_w2.get("first_message", 0) + ch_w2.get("priority_dispatched", 0)
    ok_w2 = (
        closed_lead is not None
        and active_after_close < active_before_close
        and disp2 >= 1
    )
    _record_result(
        results,
        "D3 libera slot ao encerrar conversa",
        ok_w2,
        f"lead_fechado={closed_lead} slots {active_before_close}->{active_after_close} "
        f"dispatched={disp2} pq={pq_after}",
    )
    _cleanup(client, h, camp_w, agent_w, "whatsapp")

    print("\n=== D4 campanhas_simultaneas=1 (duas campanhas mesmo agente+canal) ===")
    agent_c = client.post(
        f"{BASE}/agents/",
        headers=h,
        json={"name": f"LayerD camp{tag}", "mode": "ACTIVE", "description": "D4", "config": {}},
    ).json()["id"]
    client.put(
        f"{BASE}/agents/{agent_c}/channel-settings/whatsapp",
        headers=h,
        json={"params": {**WIDE_MSG, "campanhas_simultaneas": 1, "chats_simultaneos": 5}},
    )
    camps: list[str] = []
    for i in range(2):
        camp = client.post(
            f"{BASE}/campaigns/",
            headers=h,
            json={
                "name": f"Camp D4-{i}",
                "agent_id": agent_c,
                "channel_types": ["whatsapp"],
            },
        ).json()
        camps.append(camp["id"])
        base = client.post(
            f"{BASE}/lead-bases/",
            headers=h,
            json={
                "campaign_id": camp["id"],
                "data_recebimento": date.today().isoformat(),
                "channel_types": ["whatsapp"],
            },
        ).json()
        client.post(
            f"{BASE}/leads/",
            headers=h,
            json={
                "lead_base_id": base["id"],
                "nome_cliente": f"Lead D4-{i}",
                "telefone_1": f"+5511999{tag}{i}",
                "aux_values": {},
            },
        )
        client.post(
            f"{BASE}/campaigns/{camp['id']}/activations/whatsapp/start",
            headers=h,
        )
        time.sleep(0.05)
    _clear_agent_channel_slots(agent_c, "whatsapp")
    stats_c = await _run_scheduler()
    camp_stats = {
        cid: stats_c.get("by_channel", {}).get(f"{cid}:whatsapp", {})
        for cid in camps
    }
    processed_n = sum(1 for s in camp_stats.values() if s.get("campaigns_processed"))
    waiting_n = sum(1 for s in camp_stats.values() if s.get("campaigns_waiting"))
    ok_c = processed_n == 1 and waiting_n == 1
    _record_result(
        results,
        "D4 uma campanha processada por ciclo",
        ok_c,
        f"camps={camp_stats} processed={processed_n} waiting={waiting_n}",
    )
    for cid in camps:
        _cleanup(client, h, cid, agent_c, "whatsapp")

    print("\n=== D5 Atomicidade try_acquire (limit=1) ===")
    ok_at, det_at = await validate_atomicity(agent_c, "voice")
    _record_result(results, "D5 atomicidade paralela", ok_at, det_at)

    print("\n=== D6 Idempotência scheduler 2x ===")
    agent_i, camp_i, _ = _create_setup(client, h, f"i{tag}", "voice", 2, VOICE_PARAMS)
    _clear_agent_channel_slots(agent_i, "voice")
    s_a = await _run_scheduler()
    s_b = await _run_scheduler()
    pq_i = priority_queue_size(agent_i, "voice")
    total_enq = s_a.get("leads_enqueued", 0) + s_b.get("leads_enqueued", 0)
    ok_i = total_enq <= 2 and pq_i <= 2
    _record_result(
        results,
        "D6 idempotência 2x scheduler",
        ok_i,
        f"enq_total={total_enq} pq={pq_i} run1={s_a.get('leads_enqueued')} run2={s_b.get('leads_enqueued')}",
    )
    _cleanup(client, h, camp_i, agent_i, "voice")

    print("\n=== D7 TTL slot fantasma ===")
    ok_ttl, det_ttl = await validate_ttl_phantom(agent_i, "voice")
    _record_result(results, "D7 TTL libera slot fantasma", ok_ttl, det_ttl)

    return results


def main() -> int:
    print("Camada D — validação de concorrência")
    print(f"REDIS_URL={settings.redis_url}")
    failures = 0
    with httpx.Client(timeout=60.0) as client:
        try:
            token = login(client)
        except Exception as exc:
            print(f"FALHA login/API: {exc}")
            return 1
        h = auth_headers(token)
        results = asyncio.run(run_validation_async(client, h))

    print("\n=== RESUMO ===")
    for name, ok, detail in results:
        mark = "OK" if ok else "FALHA"
        print(f"  [{mark}] {name}: {detail}")
        if not ok:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
