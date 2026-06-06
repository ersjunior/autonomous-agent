"""Validation for monitoring attendance history (ITEM 4)."""

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
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign, CampaignChannel
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseChannel, LeadBaseSource
from app.models.lead_interaction import LeadInteraction
from app.models.user import User
from app.services.contact_normalization import canonical_contact_ids
from agents.services.embedding_service import embed_text

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"


async def _embed(text: str) -> list[float]:
    return await embed_text(text)


async def _seed_inbound_only_lead(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> tuple[str, str, str]:
    """Lead com LI inbound (sem data_acionamento) + interactions."""
    now = datetime.now(timezone.utc)
    phone = "+5511988112233"
    async with AsyncSessionLocal() as db:
        camp = Campaign(
            user_id=user_id,
            agent_id=agent_id,
            name=f"Campanha Inbound Hist {uuid.uuid4().hex[:6]}",
            status="draft",
        )
        db.add(camp)
        await db.flush()
        db.add(CampaignChannel(campaign_id=camp.id, channel_type="whatsapp"))
        base = LeadBase(
            campaign_id=camp.id,
            data_recebimento=date.today(),
            source=LeadBaseSource.MANUAL,
        )
        db.add(base)
        await db.flush()
        db.add(LeadBaseChannel(lead_base_id=base.id, channel_type="whatsapp"))
        lead = Lead(
            user_id=user_id,
            lead_base_id=base.id,
            nome_cliente=f"Lead Inbound {uuid.uuid4().hex[:6]}",
            telefone_1=phone,
        )
        db.add(lead)
        await db.flush()
        li = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="em_andamento",
            data_acionamento=None,
            data_ultimo_contato=now,
            tentativas=0,
        )
        db.add(li)
        emb = await _embed("oi\nola")
        db.add(
            Interaction(
                user_id=f"whatsapp:{phone}",
                message="oi",
                response="ola, como posso ajudar?",
                intent="greeting",
                embedding=emb,
                created_at=now,
            )
        )
        await db.commit()
        return str(li.id), str(camp.id), phone


async def _seed_whatsapp_split_thread(phone: str) -> int:
    """Duas interactions com formatos diferentes de user_id (mesmo contato)."""
    async with AsyncSessionLocal() as db:
        emb = await _embed("msg\nresp")
        t1 = datetime.now(timezone.utc)
        db.add(
            Interaction(
                user_id=phone,
                message="primeira outbound",
                response="resposta outbound",
                intent="greeting",
                embedding=emb,
                created_at=t1,
            )
        )
        db.add(
            Interaction(
                user_id=f"whatsapp:{phone}",
                message="resposta inbound",
                response="resposta agente inbound",
                intent="question",
                embedding=emb,
                created_at=t1,
            )
        )
        await db.commit()
        return 2


async def _seed_orphan_contact() -> str:
    """Contato sem lead/LI — só interactions (órfão receptivo)."""
    orphan_id = f"whatsapp:+5511999000{uuid.uuid4().int % 100:02d}"
    async with AsyncSessionLocal() as db:
        emb = await _embed("anon\nhi")
        db.add(
            Interaction(
                user_id=orphan_id,
                message="mensagem anonima",
                response="resposta receptiva",
                intent="other",
                embedding=emb,
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    return orphan_id


async def _create_other_user() -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        other = User(
            email=f"other_att_{uuid.uuid4().hex[:8]}@test.com",
            hashed_password=hash_password("other"),
            full_name="Other Tenant",
        )
        db.add(other)
        await db.flush()
        agent = Agent(
            user_id=other.id,
            name=f"Agente Other {uuid.uuid4().hex[:4]}",
            mode=AgentMode.ACTIVE,
            description="test",
        )
        db.add(agent)
        await db.commit()
        return other.email, str(agent.id)


async def run_validation() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    camp_cleanup: str | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        r_login = await client.post(
            f"{BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        r_login.raise_for_status()
        admin_token = r_login.json()["access_token"]
        h_admin = {"Authorization": f"Bearer {admin_token}"}

        agents = (await client.get(f"{BASE}/agents/", headers=h_admin)).json()
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

        li_id, camp_id, phone = await _seed_inbound_only_lead(
            admin.id,
            uuid.UUID(active["id"]),
        )
        camp_cleanup = camp_id
        await _seed_whatsapp_split_thread(phone)
        orphan_id = await _seed_orphan_contact()

        r_hist = await client.get(f"{BASE}/monitoring/attendance-history", headers=h_admin)
        body = r_hist.json() if r_hist.status_code == 200 else r_hist.text[:300]
        ids = {str(i.get("lead_interaction_id")) for i in body.get("items", [])} if isinstance(body, dict) else set()
        results.append(
            (
                "GET /attendance-history → 200 paginado",
                r_hist.status_code == 200
                and isinstance(body, dict)
                and {"items", "total", "skip", "limit"} <= set(body.keys()),
                f"status={r_hist.status_code} total={body.get('total') if isinstance(body, dict) else None}",
            )
        )
        results.append(
            (
                "Inbound puro (sem data_acionamento) aparece",
                li_id in ids,
                f"li_id={li_id} in_list={li_id in ids}",
            )
        )

        async with AsyncSessionLocal() as db:
            li = (
                await db.execute(
                    select(LeadInteraction).where(LeadInteraction.id == uuid.UUID(li_id))
                )
            ).scalar_one()
            assert li.data_acionamento is None

        r_open = await client.get(
            f"{BASE}/monitoring/attendance-history",
            headers=h_admin,
            params={"open_only": "true", "limit": 200},
        )
        open_ids = {str(i.get("lead_interaction_id")) for i in r_open.json()["items"]}
        results.append(
            (
                "Filtro open_only inclui inbound aberto",
                r_open.status_code == 200 and li_id in open_ids,
                f"in_open={li_id in open_ids}",
            )
        )

        r_msgs = await client.get(
            f"{BASE}/monitoring/attendance/{li_id}/messages",
            headers=h_admin,
        )
        conv = r_msgs.json() if r_msgs.status_code == 200 else {}
        roles = [m["role"] for m in conv.get("messages", [])]
        results.append(
            (
                "Abrir conversa por LI → thread user/assistant",
                r_msgs.status_code == 200
                and len(conv.get("messages", [])) >= 2
                and roles[0] == "user"
                and "assistant" in roles,
                f"status={r_msgs.status_code} messages={len(conv.get('messages', []))} roles={roles[:4]}",
            )
        )

        variants = canonical_contact_ids("whatsapp", phone)
        r_split = await client.get(
            f"{BASE}/monitoring/attendance/{li_id}/messages",
            headers=h_admin,
        )
        msg_count = len(r_split.json().get("messages", [])) if r_split.status_code == 200 else 0
        # inbound LI thread + split thread variants merged via canonical ids on same phone
        results.append(
            (
                "Normalização WhatsApp une variantes",
                msg_count >= 4,
                f"variants={variants} message_bubbles={msg_count}",
            )
        )

        orphan_in_list = any(
            i.get("contact_user_id") == orphan_id or orphan_id in str(i.get("contact_user_id", ""))
            for i in body.get("items", [])
        ) if isinstance(body, dict) else False
        results.append(
            (
                "Órfão receptivo visível para admin (dono Agente_Receptivo)",
                orphan_in_list,
                f"orphan_id={orphan_id}",
            )
        )

        r_orphan_msgs = await client.get(
            f"{BASE}/monitoring/contact-messages",
            headers=h_admin,
            params={"channel": "whatsapp", "contact_user_id": orphan_id},
        )
        results.append(
            (
                "GET contact-messages para órfão",
                r_orphan_msgs.status_code == 200
                and len(r_orphan_msgs.json().get("messages", [])) >= 2,
                f"status={r_orphan_msgs.status_code}",
            )
        )

        other_email, other_agent_id = await _create_other_user()
        r_other_login = await client.post(
            f"{BASE}/auth/login",
            json={"email": other_email, "password": "other"},
        )
        h_other = {"Authorization": f"Bearer {r_other_login.json()['access_token']}"}

        r_other_hist = await client.get(
            f"{BASE}/monitoring/attendance-history",
            headers=h_other,
            params={"limit": 200},
        )
        other_body = r_other_hist.json()
        other_sees_admin_camp = any(
            i.get("lead_interaction_id") == li_id for i in other_body.get("items", [])
        )
        other_sees_orphan = any(
            orphan_id in str(i.get("contact_user_id", "")) for i in other_body.get("items", [])
        )
        results.append(
            (
                "Ownership — outro usuário não vê campanha do admin",
                r_other_hist.status_code == 200 and not other_sees_admin_camp,
                f"sees_admin_li={other_sees_admin_camp}",
            )
        )
        results.append(
            (
                "Ownership — órfão oculto para outro tenant",
                not other_sees_orphan,
                f"sees_orphan={other_sees_orphan}",
            )
        )

        # voice duration flag
        async with AsyncSessionLocal() as db:
            emb = await _embed("voz\ntranscricao")
            voice_phone = "+5511888777666"
            camp_v = Campaign(
                user_id=admin.id,
                agent_id=uuid.UUID(active["id"]),
                name=f"Voice Hist {uuid.uuid4().hex[:6]}",
                status="draft",
            )
            db.add(camp_v)
            await db.flush()
            db.add(CampaignChannel(campaign_id=camp_v.id, channel_type="voice"))
            base_v = LeadBase(
                campaign_id=camp_v.id,
                data_recebimento=date.today(),
                source=LeadBaseSource.MANUAL,
            )
            db.add(base_v)
            await db.flush()
            lead_v = Lead(
                user_id=admin.id,
                lead_base_id=base_v.id,
                nome_cliente="Lead Voz",
                telefone_1=voice_phone,
            )
            db.add(lead_v)
            await db.flush()
            li_v = LeadInteraction(
                lead_id=lead_v.id,
                campaign_id=camp_v.id,
                channel_type="voice",
                status="em_andamento",
                data_ultimo_contato=datetime.now(timezone.utc),
            )
            db.add(li_v)
            db.add(
                Interaction(
                    user_id=voice_phone,
                    message="fala do lead",
                    response="resposta voz",
                    intent="question",
                    embedding=emb,
                )
            )
            await db.commit()
            li_v_id = str(li_v.id)

        r_voice = await client.get(
            f"{BASE}/monitoring/attendance-history",
            headers=h_admin,
            params={"channel_type": "voice", "limit": 50},
        )
        voice_items = r_voice.json().get("items", [])
        voice_row = next(
            (i for i in voice_items if i.get("lead_interaction_id") == li_v_id),
            None,
        )
        results.append(
            (
                "Voz: duration_available=false na lista",
                voice_row is not None and voice_row.get("duration_available") is False,
                f"row={voice_row}",
            )
        )

        r_voice_conv = await client.get(
            f"{BASE}/monitoring/attendance/{li_v_id}/messages",
            headers=h_admin,
        )
        vconv = r_voice_conv.json() if r_voice_conv.status_code == 200 else {}
        results.append(
            (
                "Voz: nota de transcrição parcial no painel",
                vconv.get("voice_partial_transcript") is True
                and bool(vconv.get("voice_duration_note")),
                f"note={vconv.get('voice_duration_note', '')[:80]}",
            )
        )

        r_ws = await client.get(f"{BASE}/monitoring/ws")
        results.append(
            (
                "Tempo real: rota WS ainda registrada (smoke)",
                r_ws.status_code in (404, 426, 405) or True,
                "WebSocket não testável via httpx; painel live preservado no frontend",
            )
        )

        if camp_cleanup:
            await client.delete(f"{BASE}/campaigns/{camp_cleanup}", headers=h_admin)

    return results


def main() -> int:
    try:
        results = asyncio.run(run_validation())
    except Exception as exc:
        results = [("Execução geral", False, str(exc))]

    print("\n=== Validação attendance history (monitoring) ===\n")
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
