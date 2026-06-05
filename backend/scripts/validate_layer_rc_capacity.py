"""
Validação R-C — estimativa, Erlang C, outbound no teto global.

  docker exec autonomous-agent-backend pip install -q psutil
  docker exec -e MAX_WEIGHTED_CAPACITY_OVERRIDE=2 autonomous-agent-worker \\
    python /workspace/backend/scripts/validate_layer_rc_capacity.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("MAX_WEIGHTED_CAPACITY_OVERRIDE", "2")

from app.core import erlang
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.services.capacity_estimate import estimate_capacity, read_resources, resolve_max_weighted_capacity
from app.services.capacity_service import (
    bind_contact_capacity,
    current_global_usage,
    release_contact_capacity,
    try_acquire_global,
    try_acquire_outbound_capacity,
)
from app.services.capacity_analysis import get_capacity_analysis

BASE = os.environ.get("API_BASE_URL", "http://backend:8000/api/v1")

# Referência: A=10 Erlangs, N=14, AHT=180s, T=20s — calculadoras ~SL 95%+
REF_A = 10.0
REF_N = 14
REF_AHT = 180.0
REF_T = 20.0
# SL esperado com nossa fórmula (≈87% — alinhado a calculadoras Erlang C clássicas)
REF_SL_EXPECTED = 0.8725
REF_SL_TOLERANCE = 0.02


def test_psutil() -> tuple[bool, str]:
    res = read_resources()
    if res.cpu_cores < 1 or res.ram_total_mb < 1:
        return False, "recursos inválidos"
    est = estimate_capacity(res)
    return True, (
        f"cpu={res.cpu_cores} ram_avail={res.ram_available_mb:.0f}MB "
        f"est_max={est.max_weighted_capacity} gpu={res.gpu_signal_available}"
    )


def test_erlang_reference() -> tuple[bool, str]:
    sl = erlang.service_level(REF_N, REF_A, REF_T, REF_AHT)
    pw = erlang.erlang_c(REF_A, REF_N)
    if abs(sl - REF_SL_EXPECTED) > REF_SL_TOLERANCE:
        return False, f"SL={sl:.4f} fora de {REF_SL_EXPECTED}±{REF_SL_TOLERANCE} (Pw={pw:.4f})"
    n_req = erlang.required_agents(REF_A, 0.80, REF_T, REF_AHT)
    sl_at_n = erlang.service_level(n_req, REF_A, REF_T, REF_AHT)
    if sl_at_n < 0.80:
        return False, f"required_N={n_req} SL={sl_at_n:.4f} < 80%"
    return True, f"SL={sl:.4f} Pw={pw:.4f} required_N(80%)={n_req} SL@N={sl_at_n:.4f}"


def test_outbound_global_gate() -> tuple[bool, str]:
    import redis as sync_redis

    from app.services.receptive_queue import queue_size

    client = sync_redis.from_url(settings.redis_url, decode_responses=True)
    for pat in (
        "receptive_queue:*",
        "queue_payload:*",
        "global_capacity*",
        "contact_capacity:*",
        "outbound_capacity:*",
        "slots_set:*",
        "slot_holder:*",
    ):
        for k in client.scan_iter(pat):
            client.delete(k)

    settings.max_weighted_capacity_override = 2
    max_cap = resolve_max_weighted_capacity()

    t1 = try_acquire_global(1, max_capacity=max_cap)
    t2 = try_acquire_global(1, max_capacity=max_cap)
    t3 = try_acquire_global(1, max_capacity=max_cap)
    if t3 is not None:
        return False, "3º acquire global deveria falhar com max=2"

    params = {"chats_simultaneos": 5, "receptivo_horario_inicio": "00:00", "receptivo_horario_fim": "23:59"}
    aid = "5dd75a41-9fc2-4fbe-87ea-851494dbf8c9"
    outbound = try_acquire_outbound_capacity(aid, "whatsapp", params)
    if outbound is not None:
        return False, "outbound deveria falhar com global cheio"

    from app.services.capacity_service import release_global

    release_global(t1, 1)
    outbound2 = try_acquire_outbound_capacity(aid, "whatsapp", params)
    if outbound2 is None:
        return False, "outbound deveria adquirir após liberar 1 unidade"

    release_global(t2, 1)
    return True, f"global cheio bloqueou outbound; após release ok usage={current_global_usage()}"


async def test_api() -> tuple[bool, str]:
    async with AsyncSessionLocal() as db:
        payload = await get_capacity_analysis(db)
    if payload.estimate.max_weighted_capacity_effective < 1:
        return False, "max efetivo inválido"
    return True, (
        f"λ={payload.observed.arrival_rate_per_hour} AHT={payload.observed.aht_seconds} "
        f"source={payload.observed.aht_source} SL={payload.erlang.service_level_predicted:.2%}"
    )


async def test_api_http() -> tuple[bool, str]:
    r = httpx.post(
        f"{BASE}/auth/login",
        json={"email": "admin@admin.com", "password": "admin"},
        timeout=30.0,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    res = httpx.get(f"{BASE}/capacity", headers={"Authorization": f"Bearer {token}"}, timeout=30.0)
    if res.status_code != 200:
        return False, res.text[:200]
    data = res.json()
    return True, json.dumps(
        {
            "global_max": data["estimate"]["max_weighted_capacity_effective"],
            "usage": data["usage"]["global_usage"],
            "aht_source": data["observed"]["aht_source"],
            "erlang_sl": data["erlang"]["service_level_predicted"],
        },
        ensure_ascii=False,
    )


async def main() -> int:
    tests = [
        ("psutil + estimate_capacity", test_psutil()),
        ("Erlang C referência A=10 N=14", test_erlang_reference()),
        ("Outbound bloqueado com global cheio", test_outbound_global_gate()),
        ("GET /capacity (serviço)", await test_api()),
        ("GET /capacity (HTTP)", await test_api_http()),
    ]
    ok_all = True
    for name, result in tests:
        if asyncio.iscoroutine(result):
            ok, detail = await result
        else:
            ok, detail = result
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
        ok_all = ok_all and ok
    await engine.dispose()
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
