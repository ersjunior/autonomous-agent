"""Validation for GET /activation/history and POST /activation/interactions/{id}/finalize."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.campaign import Campaign, CampaignChannel
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseChannel, LeadBaseSource
from app.models.lead_interaction import LeadInteraction
from app.models.user import User
from app.services.human_handoff import enter_human_mode, is_in_human_mode
from worker.tasks.outbound_campaign import _resolve_recipient

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"


async def _seed_history_fixtures(
    admin_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        other = User(
            email=f"other_hist_{uuid.uuid4().hex[:8]}@test.com",
            hashed_password=hash_password("other"),
            full_name="Other User",
        )
        db.add(other)
        await db.flush()

        camp = Campaign(
            user_id=admin_id,
            agent_id=agent_id,
            name=f"Campanha Hist {uuid.uuid4().hex[:6]}",
            status="draft",
        )
        db.add(camp)
        await db.flush()
        db.add(CampaignChannel(campaign_id=camp.id, channel_type="whatsapp"))
        db.add(CampaignChannel(campaign_id=camp.id, channel_type="telegram"))

        other_camp = Campaign(
            user_id=other.id,
            agent_id=agent_id,
            name=f"Campanha Outro {uuid.uuid4().hex[:6]}",
            status="draft",
        )
        db.add(other_camp)
        await db.flush()
        db.add(CampaignChannel(campaign_id=other_camp.id, channel_type="whatsapp"))

        base = LeadBase(
            campaign_id=camp.id,
            data_recebimento=date.today(),
            source=LeadBaseSource.MANUAL,
        )
        db.add(base)
        await db.flush()
        db.add(LeadBaseChannel(lead_base_id=base.id, channel_type="whatsapp"))
        db.add(LeadBaseChannel(lead_base_id=base.id, channel_type="telegram"))

        lead = Lead(
            user_id=admin_id,
            lead_base_id=base.id,
            nome_cliente=f"Lead Hist {uuid.uuid4().hex[:6]}",
            telefone_1="+5511988776655",
            aux_values={"telegram_id": "9988776655"},
        )
        db.add(lead)
        await db.flush()

        li_open = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="em_andamento",
            data_acionamento=now,
            tentativas=1,
        )
        li_no_date = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="pendente",
            data_acionamento=None,
            tentativas=0,
        )
        li_telegram = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="telegram",
            status="acionado",
            data_acionamento=now,
            tentativas=1,
        )
        li_terminal = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="convertido",
            data_acionamento=now,
            tentativas=2,
        )
        li_other = LeadInteraction(
            lead_id=lead.id,
            campaign_id=other_camp.id,
            channel_type="whatsapp",
            status="em_andamento",
            data_acionamento=now,
            tentativas=1,
        )
        for row in (li_open, li_no_date, li_telegram, li_terminal, li_other):
            db.add(row)
        await db.commit()

        recipient = _resolve_recipient(lead, "whatsapp") or ""
        return {
            "camp_id": str(camp.id),
            "other_camp_id": str(other_camp.id),
            "lead_id": str(lead.id),
            "li_open": str(li_open.id),
            "li_no_date": str(li_no_date.id),
            "li_telegram": str(li_telegram.id),
            "li_terminal": str(li_terminal.id),
            "li_other": str(li_other.id),
            "recipient": recipient,
        }


async def _reload_interaction(interaction_id: str) -> LeadInteraction | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LeadInteraction)
            .options(selectinload(LeadInteraction.tabulacao))
            .where(LeadInteraction.id == uuid.UUID(interaction_id))
        )
        return result.scalar_one_or_none()


async def run_validation() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    camp_id: str | None = None
    other_camp_id: str | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        r_login = await client.post(
            f"{BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        r_login.raise_for_status()
        h = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

        agents = (await client.get(f"{BASE}/agents/", headers=h)).json()
        active = next((a for a in agents if a.get("mode") == "ACTIVE"), None)
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
            fixtures = await _seed_history_fixtures(admin.id, uuid.UUID(active["id"]))

        camp_id = fixtures["camp_id"]
        other_camp_id = fixtures["other_camp_id"]

        r_hist = await client.get(f"{BASE}/activation/history", headers=h)
        body = r_hist.json() if r_hist.status_code == 200 else r_hist.text[:300]
        ids_in_list = {item["id"] for item in body.get("items", [])} if isinstance(body, dict) else set()
        results.append(
            (
                "GET /activation/history → 200 paginado",
                r_hist.status_code == 200
                and isinstance(body, dict)
                and {"items", "total", "skip", "limit"} <= set(body.keys()),
                f"status={r_hist.status_code} total={body.get('total') if isinstance(body, dict) else None}",
            )
        )
        results.append(
            (
                "Sem data_acionamento não aparece",
                fixtures["li_no_date"] not in ids_in_list,
                f"li_no_date in list={fixtures['li_no_date'] in ids_in_list}",
            )
        )
        results.append(
            (
                "Ownership — campanha de outro usuário oculta",
                fixtures["li_other"] not in ids_in_list,
                f"li_other in list={fixtures['li_other'] in ids_in_list}",
            )
        )

        r_camp = await client.get(
            f"{BASE}/activation/history",
            headers=h,
            params={"campaign_id": camp_id, "limit": 200},
        )
        camp_body = r_camp.json()
        camp_ids = {item["id"] for item in camp_body["items"]}
        results.append(
            (
                "Filtro campaign_id",
                r_camp.status_code == 200
                and fixtures["li_open"] in camp_ids
                and fixtures["li_other"] not in camp_ids,
                f"count={len(camp_body['items'])}",
            )
        )

        r_ch = await client.get(
            f"{BASE}/activation/history",
            headers=h,
            params={"channel_type": "telegram", "campaign_id": camp_id, "limit": 200},
        )
        ch_body = r_ch.json()
        ch_ids = {item["id"] for item in ch_body["items"]}
        results.append(
            (
                "Filtro channel_type=telegram",
                r_ch.status_code == 200
                and fixtures["li_telegram"] in ch_ids
                and fixtures["li_open"] not in ch_ids,
                f"ids={ch_ids}",
            )
        )

        r_st = await client.get(
            f"{BASE}/activation/history",
            headers=h,
            params={"status": "convertido", "campaign_id": camp_id, "limit": 200},
        )
        st_body = r_st.json()
        st_ids = {item["id"] for item in st_body["items"]}
        results.append(
            (
                "Filtro status=convertido",
                r_st.status_code == 200
                and fixtures["li_terminal"] in st_ids
                and fixtures["li_open"] not in st_ids,
                f"ids={st_ids}",
            )
        )

        r_open = await client.get(
            f"{BASE}/activation/history",
            headers=h,
            params={"open_only": "true", "campaign_id": camp_id, "limit": 200},
        )
        open_body = r_open.json()
        open_ids = {item["id"] for item in open_body["items"]}
        results.append(
            (
                "Filtro open_only=true",
                r_open.status_code == 200
                and fixtures["li_open"] in open_ids
                and fixtures["li_terminal"] not in open_ids,
                f"ids={open_ids}",
            )
        )

        recipient = fixtures["recipient"]
        if recipient:
            enter_human_mode("whatsapp", recipient)
            in_human_before = is_in_human_mode("whatsapp", recipient)
        else:
            in_human_before = False

        r_fin = await client.post(
            f"{BASE}/activation/interactions/{fixtures['li_open']}/finalize",
            headers=h,
            json={"tabulacao_codigo": "NEG:SUCESSO"},
        )
        fin_body = r_fin.json() if r_fin.status_code == 200 else r_fin.text[:300]
        li_after = await _reload_interaction(fixtures["li_open"])
        in_human_after = (
            is_in_human_mode("whatsapp", recipient) if recipient else True
        )
        results.append(
            (
                "Finalizar LI aberta NEG:SUCESSO → convertido",
                r_fin.status_code == 200
                and isinstance(fin_body, dict)
                and fin_body.get("status") == "convertido"
                and li_after is not None
                and li_after.status == "convertido"
                and li_after.tabulacao_origem == "MANUAL_FINALIZE",
                f"status={r_fin.status_code} li_status={li_after.status if li_after else None} "
                f"origem={li_after.tabulacao_origem if li_after else None}",
            )
        )
        r_open2 = await client.get(
            f"{BASE}/activation/history",
            headers=h,
            params={"open_only": "true", "campaign_id": camp_id, "limit": 200},
        )
        open2_ids = {item["id"] for item in r_open2.json()["items"]}
        results.append(
            (
                "Após finalize não aparece em open_only",
                fixtures["li_open"] not in open2_ids,
                f"in open_only={fixtures['li_open'] in open2_ids}",
            )
        )

        if recipient:
            results.append(
                (
                    "Modo humano limpo após finalize",
                    in_human_before and not in_human_after,
                    f"before={in_human_before} after={in_human_after}",
                )
            )

        r_fin2 = await client.post(
            f"{BASE}/activation/interactions/{fixtures['li_terminal']}/finalize",
            headers=h,
            json={"tabulacao_codigo": "NEG:SUCESSO"},
        )
        results.append(
            (
                "Finalizar LI terminal → 400",
                r_fin2.status_code == 400 and "encerrado" in r_fin2.text.lower(),
                f"status={r_fin2.status_code} body={r_fin2.text[:120]}",
            )
        )

        if camp_id:
            await client.delete(f"{BASE}/campaigns/{camp_id}", headers=h)
            camp_id = None
        if other_camp_id:
            await client.delete(f"{BASE}/campaigns/{other_camp_id}", headers=h)
            other_camp_id = None

    return results


def main() -> int:
    try:
        results = asyncio.run(run_validation())
    except Exception as exc:
        results = [("Execução geral", False, str(exc))]

    print("\n=== Validação activation history ===\n")
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
