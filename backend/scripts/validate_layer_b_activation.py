"""
Validação Camada B — janela de horário do motor de acionamento.

Executar no container backend:
  docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_layer_b_activation.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from app.core.activation_window import is_within_window
from app.core.config import ACTIVATION_TIMEZONE
from app.core.database import AsyncSessionLocal
from app.models.lead_interaction import LeadInteraction
from app.services.activation_service import get_pending_leads_for_channel
from sqlalchemy import func, select
from worker.tasks.activation_scheduler import _process_active_activations_async
from worker.tasks.lead_tracking import upsert_lead_interaction

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"
TZ = ZoneInfo(ACTIVATION_TIMEZONE)

WIDE_PARAMS = {
    "chats_simultaneos": 5,
    "campanhas_simultaneas": 1,
    "tentativas_sem_resposta": 2,
    "minutos_segunda_mensagem": 20,
    "horario_inicio": "00:00",
    "horario_fim": "23:59",
}
NARROW_PARAMS = {**WIDE_PARAMS, "horario_inicio": "02:00", "horario_fim": "03:00"}


def login(client: httpx.Client) -> str:
    r = client.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 6, 4, hour, minute, tzinfo=TZ)


def test_is_within_window_unit() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    def check(name: str, expected: bool, **kwargs) -> None:
        got = is_within_window(**kwargs)
        cases.append((name, got == expected, f"expected={expected} got={got}"))

    check(
        "09:00–20:00 às 10:00 → dentro",
        True,
        horario_inicio="09:00",
        horario_fim="20:00",
        now=_dt(10, 0),
    )
    check(
        "09:00–20:00 às 08:59 → fora",
        False,
        horario_inicio="09:00",
        horario_fim="20:00",
        now=_dt(8, 59),
    )
    check(
        "09:00–20:00 às 09:00 (borda início) → dentro",
        True,
        horario_inicio="09:00",
        horario_fim="20:00",
        now=_dt(9, 0),
    )
    check(
        "09:00–20:00 às 20:00 (borda fim) → fora",
        False,
        horario_inicio="09:00",
        horario_fim="20:00",
        now=_dt(20, 0),
    )
    check(
        "02:00–03:00 às 14:00 → fora",
        False,
        horario_inicio="02:00",
        horario_fim="03:00",
        now=_dt(14, 0),
    )
    check(
        "00:00–23:59 às 14:00 → dentro",
        True,
        horario_inicio="00:00",
        horario_fim="23:59",
        now=_dt(14, 0),
    )
    return cases


async def count_interactions(campaign_id: str, channel: str) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count())
            .select_from(LeadInteraction)
            .where(
                LeadInteraction.campaign_id == uuid.UUID(campaign_id),
                LeadInteraction.channel_type == channel,
            )
        )
        return int(result.scalar_one())


async def pending_count(campaign_id: str, channel: str) -> int:
    async with AsyncSessionLocal() as db:
        pending = await get_pending_leads_for_channel(
            db, uuid.UUID(campaign_id), channel
        )
        return len(pending)


def _create_agent_campaign_leads(
    client: httpx.Client,
    h: dict[str, str],
    tag: str,
    lead_count: int = 3,
) -> tuple[str, str, list[str]]:
    agent = client.post(
        f"{BASE}/agents/",
        headers=h,
        json={
            "name": f"LayerB {tag}",
            "mode": "ACTIVE",
            "description": "validação camada B",
            "config": {},
        },
    ).json()
    agent_id = agent["id"]

    camp = client.post(
        f"{BASE}/campaigns/",
        headers=h,
        json={
            "name": f"Camp B {tag}",
            "agent_id": agent_id,
            "channel_types": ["whatsapp"],
        },
    ).json()
    campaign_id = camp["id"]

    base = client.post(
        f"{BASE}/lead-bases/",
        headers=h,
        json={
            "campaign_id": campaign_id,
            "data_recebimento": date.today().isoformat(),
            "channel_types": ["whatsapp"],
        },
    ).json()

    lead_ids: list[str] = []
    for i in range(1, lead_count + 1):
        lead = client.post(
            f"{BASE}/leads/",
            headers=h,
            json={
                "lead_base_id": base["id"],
                "nome_cliente": f"Lead B{i}",
                "telefone_1": f"+5511988{tag[:4]}{i:03d}",
                "aux_values": {},
            },
        ).json()
        lead_ids.append(lead["id"])
    return agent_id, campaign_id, lead_ids


def _cleanup(client: httpx.Client, h: dict[str, str], campaign_id: str, agent_id: str) -> None:
    try:
        client.post(
            f"{BASE}/campaigns/{campaign_id}/activations/whatsapp/stop",
            headers=h,
        )
    except Exception:
        pass
    client.delete(f"{BASE}/campaigns/{campaign_id}", headers=h)
    client.delete(f"{BASE}/agents/{agent_id}", headers=h)


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    results.extend(test_is_within_window_unit())

    client = httpx.Client(timeout=120.0)
    tag = uuid.uuid4().hex[:8]

    try:
        token = login(client)
        h = auth_headers(token)

        # --- Campanha 1: fora → retomada → idempotência ---
        agent_id, campaign_id, lead_ids = _create_agent_campaign_leads(client, h, tag)
        lead_count = len(lead_ids)

        client.put(
            f"{BASE}/agents/{agent_id}/channel-settings/whatsapp",
            headers=h,
            json={"params": NARROW_PARAMS},
        )
        r_start_out = client.post(
            f"{BASE}/campaigns/{campaign_id}/activations/whatsapp/start",
            headers=h,
        )
        body_out = r_start_out.json()
        results.append(
            (
                "FORA janela: start liga motor sem disparar",
                r_start_out.status_code == 200
                and body_out.get("activation", {}).get("is_running") is True
                and body_out.get("dispatched_now", 0) == 0
                and body_out.get("reason")
                and "fora da janela" in body_out.get("reason", ""),
                json.dumps(body_out)[:240],
            )
        )

        async def run_async_phase_narrow() -> dict:
            from app.core.database import engine

            ix0 = await count_interactions(campaign_id, "whatsapp")
            stats_out = await _process_active_activations_async()
            await engine.dispose()
            return {"ix0": ix0, "stats_out": stats_out}

        narrow_phase = asyncio.run(run_async_phase_narrow())

        results.append(
            (
                "FORA janela: zero LeadInteraction após start",
                narrow_phase["ix0"] == 0,
                f"count={narrow_phase['ix0']}",
            )
        )
        stats_out = narrow_phase["stats_out"]
        key = f"{campaign_id}:whatsapp"
        enqueued_ours_out = stats_out.get("by_channel", {}).get(key, 0)
        results.append(
            (
                "FORA janela: scheduler não enfileira",
                enqueued_ours_out == 0,
                f"ours={enqueued_ours_out} stats={stats_out}",
            )
        )

        client.put(
            f"{BASE}/agents/{agent_id}/channel-settings/whatsapp",
            headers=h,
            json={"params": WIDE_PARAMS},
        )

        async def run_async_phase_resume() -> dict:
            from app.core.database import engine

            pending_before = await pending_count(campaign_id, "whatsapp")
            stats_resume = await _process_active_activations_async()
            async with AsyncSessionLocal() as db:
                for lid in lead_ids:
                    await upsert_lead_interaction(
                        db,
                        uuid.UUID(lid),
                        uuid.UUID(campaign_id),
                        "whatsapp",
                        status="acionado",
                        set_acionamento=True,
                    )
                await db.commit()
            ix_after = await count_interactions(campaign_id, "whatsapp")
            stats_idem = await _process_active_activations_async()
            await engine.dispose()
            return {
                "pending_before": pending_before,
                "stats_resume": stats_resume,
                "ix_after": ix_after,
                "stats_idem": stats_idem,
            }

        resume_phase = asyncio.run(run_async_phase_resume())
        stats_resume = resume_phase["stats_resume"]
        pending_before = resume_phase["pending_before"]
        enqueued_ours_resume = stats_resume.get("by_channel", {}).get(key, 0)
        results.append(
            (
                "RETOMADA: scheduler enfileira pendentes na janela",
                pending_before == lead_count and enqueued_ours_resume == lead_count,
                f"pending={pending_before} ours={enqueued_ours_resume} stats={stats_resume}",
            )
        )

        ix_after = resume_phase["ix_after"]
        results.append(
            (
                "Worker simulado: LeadInteraction criada",
                ix_after >= lead_count,
                f"count={ix_after}",
            )
        )

        stats_idem = resume_phase["stats_idem"]
        enqueued_ours_idem = stats_idem.get("by_channel", {}).get(key, 0)
        results.append(
            (
                "Idempotência: 2ª execução scheduler → 0 novos",
                enqueued_ours_idem == 0,
                f"ours={enqueued_ours_idem} stats={stats_idem}",
            )
        )

        _cleanup(client, h, campaign_id, agent_id)

        # --- Campanha 2: start imediato DENTRO da janela ---
        tag2 = uuid.uuid4().hex[:8]
        agent2, camp2, _ = _create_agent_campaign_leads(client, h, tag2, lead_count=2)
        client.put(
            f"{BASE}/agents/{agent2}/channel-settings/whatsapp",
            headers=h,
            json={"params": WIDE_PARAMS},
        )
        r_start_in = client.post(
            f"{BASE}/campaigns/{camp2}/activations/whatsapp/start",
            headers=h,
        )
        body_in = r_start_in.json()
        results.append(
            (
                "DENTRO janela: start dispara pendentes",
                r_start_in.status_code == 200
                and body_in.get("activation", {}).get("is_running") is True
                and body_in.get("dispatched_now", 0) == 2,
                json.dumps(body_in)[:240],
            )
        )
        _cleanup(client, h, camp2, agent2)

        print("\n=== Validação Camada B — Janela de Horário ===\n")
        all_ok = True
        for name, ok, detail in results:
            mark = "OK" if ok else "FALHA"
            if not ok:
                all_ok = False
            print(f"[{mark}] {name}")
            print(f"       {detail}\n")
        return 0 if all_ok else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
