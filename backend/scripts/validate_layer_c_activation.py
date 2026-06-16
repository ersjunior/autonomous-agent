"""
Validação Camada C — cadência e tentativas (ACTIVE).

Executar no container backend:
  docker exec autonomous-agent-backend alembic upgrade head
  docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_layer_c_activation.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.lead_interaction import LeadInteraction
from app.services.activation_cadence import (
    count_recent_dispatches,
    lead_has_responded,
    leads_needing_followup,
    remaining_hourly_quota,
)
from worker.tasks.activation_scheduler import _process_active_activations_async
from worker.tasks.lead_tracking import upsert_lead_interaction

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"

WIDE_PARAMS_MSG = {
    "chats_simultaneos": 5,
    "campanhas_simultaneas": 1,
    "tentativas_sem_resposta": 2,
    "minutos_segunda_mensagem": 20,
    "horario_inicio": "00:00",
    "horario_fim": "23:59",
}
VOICE_PARAMS = {
    "chamadas_simultaneas": 1,
    "campanhas_simultaneas": 1,
    "tentativas_por_hora": 2,
    "horario_inicio": "00:00",
    "horario_fim": "23:59",
}


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
        json={"name": f"LayerC {tag}", "mode": "ACTIVE", "description": "validação C", "config": {}},
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
        json={
            "name": f"Camp C {tag}",
            "agent_id": agent_id,
            "channel_types": [channel],
        },
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
        phone = f"+5511977{tag[:4]}{i:03d}"
        lead = client.post(
            f"{BASE}/leads/",
            headers=h,
            json={
                "lead_base_id": base["id"],
                "nome_cliente": f"Lead C{i}",
                "telefone_1": phone,
                "aux_values": {},
            },
        ).json()
        lead_ids.append(lead["id"])
    client.post(
        f"{BASE}/campaigns/{campaign_id}/activations/{channel}/start",
        headers=h,
    )
    return agent_id, campaign_id, lead_ids


def _cleanup(client: httpx.Client, h: dict[str, str], campaign_id: str, agent_id: str, channel: str) -> None:
    try:
        client.post(
            f"{BASE}/campaigns/{campaign_id}/activations/{channel}/stop",
            headers=h,
        )
    except Exception:
        pass
    client.delete(f"{BASE}/campaigns/{campaign_id}", headers=h)
    client.delete(f"{BASE}/agents/{agent_id}", headers=h)


async def _run_scheduler() -> dict:
    return await _process_active_activations_async()


async def _get_interaction(campaign_id: str, lead_id: str, channel: str = "whatsapp") -> LeadInteraction:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(LeadInteraction).where(
                LeadInteraction.lead_id == uuid.UUID(lead_id),
                LeadInteraction.campaign_id == uuid.UUID(campaign_id),
                LeadInteraction.channel_type == channel,
            )
        )
        return r.scalar_one()


async def run_validation_async(client: httpx.Client, h: dict[str, str], tag: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    async with AsyncSessionLocal() as db:
        await db.execute(
            select(LeadInteraction.tentativas, LeadInteraction.data_ultima_tentativa).limit(1)
        )
    results.append(
        ("Migration: colunas tentativas/data_ultima_tentativa", True, "OK")
    )

    # --- VOZ rate limit ---
    agent_v, camp_v, leads_v = _create_setup(client, h, f"v{tag}", "voice", 5, VOICE_PARAMS)
    key_v = f"{camp_v}:voice"
    stats_v1 = await _run_scheduler()
    ch_v1 = stats_v1.get("by_channel", {}).get(key_v, {})
    enq_v1 = ch_v1.get("first_message", 0)
    quota_rem_v1 = ch_v1.get("hourly_quota_remaining", -1)
    results.append(
        (
            "VOZ: 5 pendentes, cota 2/h → enfileira no máximo 2",
            enq_v1 == 2,
            f"enqueued={enq_v1} quota_remaining={quota_rem_v1} stats_ch={ch_v1}",
        )
    )

    async with AsyncSessionLocal() as db:
        for lid in leads_v[:2]:
            await upsert_lead_interaction(
                db,
                uuid.UUID(lid),
                uuid.UUID(camp_v),
                "voice",
                status="acionado",
                set_acionamento=True,
                record_outbound_attempt=True,
            )
        await db.commit()

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    async with AsyncSessionLocal() as db:
        recent_v = await count_recent_dispatches(db, uuid.UUID(camp_v), "voice", since)
        rem_v = remaining_hourly_quota(2, recent_v)

    stats_v2 = await _run_scheduler()
    ch_v2 = stats_v2.get("by_channel", {}).get(key_v, {})
    enq_v2 = ch_v2.get("first_message", 0)
    results.append(
        (
            "VOZ: mesma hora após cota → 0 novos",
            enq_v2 == 0 and recent_v >= 2 and rem_v == 0,
            f"recent={recent_v} remaining={rem_v} enqueued2={enq_v2}",
        )
    )
    _cleanup(client, h, camp_v, agent_v, "voice")

    # --- WHATSAPP follow-up ---
    agent_w, camp_w, leads_w = _create_setup(client, h, f"w{tag}", "whatsapp", 1, WIDE_PARAMS_MSG)
    lead_w = leads_w[0]
    key_w = f"{camp_w}:whatsapp"
    old_attempt = datetime.now(timezone.utc) - timedelta(minutes=25)

    async with AsyncSessionLocal() as db:
        rec_seed = await upsert_lead_interaction(
            db,
            uuid.UUID(lead_w),
            uuid.UUID(camp_w),
            "whatsapp",
            status="acionado",
            set_acionamento=True,
            record_outbound_attempt=True,
        )
        rec_seed.data_ultima_tentativa = old_attempt
        rec_seed.tentativas = 1
        await db.commit()

    async with AsyncSessionLocal() as db:
        eligible = await leads_needing_followup(db, uuid.UUID(camp_w), "whatsapp", 20, 2)
    results.append(
        (
            "WHATSAPP: lead elegível a follow-up (sem inbound)",
            len(eligible) == 1 and not lead_has_responded(rec_seed),
            f"eligible={len(eligible)}",
        )
    )

    stats_fu = await _run_scheduler()
    fu_count = stats_fu.get("by_channel", {}).get(key_w, {}).get("followup", 0)
    results.append(
        (
            "WHATSAPP: scheduler enfileira 1 follow-up",
            fu_count == 1,
            f"followup={fu_count} stats={stats_fu.get('by_channel', {}).get(key_w)}",
        )
    )

    rec_after_queue = await _get_interaction(camp_w, lead_w)
    results.append(
        (
            "WHATSAPP: tentativas ainda 1 até worker processar follow-up",
            rec_after_queue.tentativas == 1,
            f"tentativas={rec_after_queue.tentativas}",
        )
    )

    from agents.orchestrator.router import route_message
    from app.core.activation_cadence_text import FOLLOWUP_TRIGGER_MESSAGE
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    from sqlalchemy.orm import selectinload
    from worker.tasks.outbound_campaign import _agent_context_for_campaign, get_phone

    fu_text = ""
    async with AsyncSessionLocal() as db:
        lead_row = (
            await db.execute(
                select(Lead)
                .options(selectinload(Lead.lead_base))
                .where(Lead.id == uuid.UUID(lead_w))
            )
        ).scalar_one()
        camp_row = (
            await db.execute(
                select(Campaign)
                .options(selectinload(Campaign.agent))
                .where(Campaign.id == uuid.UUID(camp_w))
            )
        ).scalar_one()
        phone = get_phone(lead_row) or ""
        ctx = await _agent_context_for_campaign(db, camp_row.agent, camp_row, lead=lead_row, followup=True)
        route_result = await route_message(
            FOLLOWUP_TRIGGER_MESSAGE,
            "whatsapp",
            phone,
            agent_context=ctx,
        )
        fu_text = (route_result.get("response") or "")[:200]

    results.append(
        (
            "WHATSAPP: texto gerado é follow-up (não abordagem inicial)",
            bool(fu_text.strip())
            and "assistente virtual" not in fu_text.lower()
            and (
                "follow-up" in fu_text.lower()
                or "ajudar" in fu_text.lower()
                or "ainda" in fu_text.lower()
            ),
            f"response_preview={fu_text!r}",
        )
    )

    async with AsyncSessionLocal() as db:
        await upsert_lead_interaction(
            db,
            uuid.UUID(lead_w),
            uuid.UUID(camp_w),
            "whatsapp",
            status="acionado",
            record_outbound_attempt=True,
            devolutiva=fu_text[:500] if fu_text else None,
        )
        await db.commit()

    rec_fu = await _get_interaction(camp_w, lead_w)
    results.append(
        ("WHATSAPP: após follow-up tentativas=2", rec_fu.tentativas == 2, f"tentativas={rec_fu.tentativas}")
    )

    stats_idem = await _run_scheduler()
    ch_idem = stats_idem.get("by_channel", {}).get(key_w, {})
    results.append(
        (
            "Idempotência: 2ª execução não duplica follow-up nem 1ª msg",
            ch_idem.get("followup", 0) == 0 and ch_idem.get("first_message", 0) == 0,
            f"stats={ch_idem}",
        )
    )
    _cleanup(client, h, camp_w, agent_w, "whatsapp")

    # --- WHATSAPP respondeu ---
    agent_r, camp_r, leads_r = _create_setup(client, h, f"r{tag}", "whatsapp", 1, WIDE_PARAMS_MSG)
    lead_r = leads_r[0]
    t_out = datetime.now(timezone.utc) - timedelta(minutes=30)
    t_in = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        rec_r = await upsert_lead_interaction(
            db,
            uuid.UUID(lead_r),
            uuid.UUID(camp_r),
            "whatsapp",
            status="em_andamento",
            set_acionamento=True,
            record_outbound_attempt=True,
        )
        rec_r.data_ultima_tentativa = t_out
        rec_r.tentativas = 1
        rec_r.data_ultimo_contato = t_in
        await db.commit()
        responded = lead_has_responded(rec_r)

    async with AsyncSessionLocal() as db:
        el_resp = len(await leads_needing_followup(db, uuid.UUID(camp_r), "whatsapp", 20, 2))
    stats_resp = await _run_scheduler()
    fu_resp = stats_resp.get("by_channel", {}).get(f"{camp_r}:whatsapp", {}).get("followup", 0)
    results.append(
        (
            "WHATSAPP respondeu: sem follow-up",
            responded and el_resp == 0 and fu_resp == 0,
            f"responded={responded} eligible={el_resp} followup={fu_resp}",
        )
    )
    _cleanup(client, h, camp_r, agent_r, "whatsapp")

    # --- ENCERRAR ---
    agent_c, camp_c, leads_c = _create_setup(client, h, f"c{tag}", "whatsapp", 1, WIDE_PARAMS_MSG)
    lead_c = leads_c[0]
    old = datetime.now(timezone.utc) - timedelta(minutes=25)
    async with AsyncSessionLocal() as db:
        rec_c = await upsert_lead_interaction(
            db,
            uuid.UUID(lead_c),
            uuid.UUID(camp_c),
            "whatsapp",
            status="acionado",
            set_acionamento=True,
            record_outbound_attempt=True,
        )
        rec_c.tentativas = 2
        rec_c.data_ultima_tentativa = old
        await db.commit()

    stats_close = await _run_scheduler()
    closed = stats_close.get("by_channel", {}).get(f"{camp_c}:whatsapp", {}).get("closed", 0)
    results.append(
        ("ENCERRAR: tentativas=max sem resposta → nao_atendido", closed == 1, f"closed={closed}")
    )

    rec_closed = await _get_interaction(camp_c, lead_c)
    results.append(
        (
            "ENCERRAR: status e devolutiva",
            rec_closed.status == "nao_atendido" and rec_closed.devolutiva is not None,
            f"status={rec_closed.status} devolutiva={rec_closed.devolutiva}",
        )
    )
    _cleanup(client, h, camp_c, agent_c, "whatsapp")

    try:
        await _process_active_activations_async()
        await _process_active_activations_async()
        results.append(("Worker/scheduler: 2x sem InterfaceError", True, "ok"))
    except Exception as exc:
        results.append(("Worker/scheduler: 2x sem InterfaceError", False, str(exc)))

    await engine.dispose()
    return results


def main() -> int:
    client = httpx.Client(timeout=120.0)
    tag = uuid.uuid4().hex[:8]
    try:
        token = login(client)
        h = auth_headers(token)
        results = asyncio.run(run_validation_async(client, h, tag))

        print("\n=== Validação Camada C — Cadência e Tentativas ===\n")
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
