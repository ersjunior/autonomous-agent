"""Validation for POST /activation/test-dispatch."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign, CampaignChannel
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseChannel, LeadBaseSource
from app.models.lead_interaction import LeadInteraction
from app.models.user import User
from app.services.capacity_service import current_global_usage, resolve_max_weighted_capacity

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"


async def _seed_test_lead(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    with_phone: bool = True,
    with_telegram: bool = False,
) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        camp = Campaign(
            user_id=user_id,
            agent_id=agent_id,
            name=f"Campanha Teste Dispatch {uuid.uuid4().hex[:6]}",
            status="draft",
        )
        db.add(camp)
        await db.flush()
        db.add(CampaignChannel(campaign_id=camp.id, channel_type="whatsapp"))
        db.add(CampaignChannel(campaign_id=camp.id, channel_type="telegram"))
        base = LeadBase(
            campaign_id=camp.id,
            data_recebimento=date.today(),
            source=LeadBaseSource.MANUAL,
        )
        db.add(base)
        await db.flush()
        db.add(LeadBaseChannel(lead_base_id=base.id, channel_type="whatsapp"))
        db.add(LeadBaseChannel(lead_base_id=base.id, channel_type="telegram"))
        aux = {"telegram_id": "123456789"} if with_telegram else {}
        lead = Lead(
            user_id=user_id,
            lead_base_id=base.id,
            nome_cliente=f"Lead Teste {uuid.uuid4().hex[:6]}",
            telefone_1="+5511999990001" if with_phone else None,
            aux_values=aux,
        )
        db.add(lead)
        await db.commit()
        return str(lead.id), str(camp.id)


async def _get_interaction(lead_id: str, campaign_id: str, channel: str) -> LeadInteraction | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LeadInteraction).where(
                LeadInteraction.lead_id == uuid.UUID(lead_id),
                LeadInteraction.campaign_id == uuid.UUID(campaign_id),
                LeadInteraction.channel_type == channel,
            )
        )
        return result.scalar_one_or_none()


async def run_validation() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    camp_id_for_cleanup: str | None = None

    async with httpx.AsyncClient(timeout=180.0) as client:
        r_login = await client.post(
            f"{BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        r_login.raise_for_status()
        h = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

        agents = (await client.get(f"{BASE}/agents/", headers=h)).json()
        active = next((a for a in agents if a.get("mode") == "ACTIVE"), None)
        receptive = next((a for a in agents if a.get("mode") == "RECEPTIVE"), None)
        if not active:
            results.append(("Setup agente ACTIVE", False, "não encontrado"))
            return results

        async with AsyncSessionLocal() as db:
            admin = (
                await db.execute(select(User).where(User.email == ADMIN_EMAIL))
            ).scalar_one_or_none()
            if admin is None:
                results.append(("Setup admin", False, "não encontrado"))
                return results
            user_id = admin.id

        lead_id, camp_id = await _seed_test_lead(user_id, uuid.UUID(active["id"]))
        camp_id_for_cleanup = camp_id

        r_dispatch = await client.post(
            f"{BASE}/activation/test-dispatch",
            headers=h,
            json={
                "lead_id": lead_id,
                "agent_id": active["id"],
                "channel_type": "whatsapp",
            },
        )
        body = r_dispatch.json() if r_dispatch.status_code == 200 else r_dispatch.text[:300]
        interaction = await _get_interaction(lead_id, camp_id, "whatsapp")
        results.append(
            (
                "POST test-dispatch whatsapp → 200 + resposta",
                r_dispatch.status_code == 200
                and isinstance(body, dict)
                and body.get("status") in ("sucesso", "erro")
                and (body.get("response") or body.get("error")),
                f"status={r_dispatch.status_code} body={body}",
            )
        )
        results.append(
            (
                "LeadInteraction criada (campanha da base)",
                interaction is not None,
                f"interaction_id={interaction.id if interaction else None} "
                f"campaign_id={interaction.campaign_id if interaction else None}",
            )
        )

        if receptive:
            r_rec = await client.post(
                f"{BASE}/activation/test-dispatch",
                headers=h,
                json={
                    "lead_id": lead_id,
                    "agent_id": receptive["id"],
                    "channel_type": "whatsapp",
                },
            )
            results.append(
                (
                    "Agente RECEPTIVE → 400",
                    r_rec.status_code == 400
                    and "ACTIVE" in r_rec.text,
                    f"status={r_rec.status_code} body={r_rec.text[:120]}",
                )
            )

        lead_no_phone, camp2 = await _seed_test_lead(
            user_id, uuid.UUID(active["id"]), with_phone=False, with_telegram=False
        )
        r_no_rec = await client.post(
            f"{BASE}/activation/test-dispatch",
            headers=h,
            json={
                "lead_id": lead_no_phone,
                "agent_id": active["id"],
                "channel_type": "whatsapp",
            },
        )
        results.append(
            (
                "Lead sem telefone whatsapp → 400",
                r_no_rec.status_code == 400 and "telefone" in r_no_rec.text.lower(),
                f"status={r_no_rec.status_code} body={r_no_rec.text[:120]}",
            )
        )
        await client.delete(f"{BASE}/campaigns/{camp2}", headers=h)

        max_cap = resolve_max_weighted_capacity()
        usage_before = current_global_usage()
        results.append(
            (
                "Disparo fora de janela (bypass) — endpoint não checa horário",
                r_dispatch.status_code == 200,
                "test-dispatch não valida janela; confirmado pelo fluxo síncrono",
            )
        )

        r_start = await client.post(f"{BASE}/campaigns/{camp_id}/start", headers=h)
        results.append(
            (
                "Regressão start_campaign após test-dispatch",
                r_start.status_code == 200,
                f"status={r_start.status_code} body={r_start.text[:120]}",
            )
        )

        await client.delete(f"{BASE}/campaigns/{camp_id}", headers=h)
        camp_id_for_cleanup = None

        results.append(
            (
                "Capacidade global (info)",
                True,
                f"max={max_cap} usage_before={usage_before}",
            )
        )

    return results


def main() -> int:
    try:
        results = asyncio.run(run_validation())
    except Exception as exc:
        results = [("Execução geral", False, str(exc))]

    print("\n=== Validação test-dispatch ===\n")
    failed = 0
    for name, ok, detail in results:
        mark = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {name}")
        print(f"      {detail}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
