"""Valida correção do worker — task outbound via fila + LeadInteraction."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.lead_interaction import LeadInteraction

BASE = "http://127.0.0.1:8000/api/v1"


async def poll_interactions(campaign_id: str, timeout: int = 90) -> list[LeadInteraction]:
    cid = uuid.UUID(campaign_id)
    for _ in range(timeout // 2):
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(LeadInteraction).where(LeadInteraction.campaign_id == cid)
                )
            ).scalars().all()
        if rows:
            return list(rows)
        await asyncio.sleep(2)
    return []


def main() -> int:
    r = httpx.post(
        f"{BASE}/auth/login",
        json={"email": "admin@admin.com", "password": "admin"},
        timeout=30.0,
    )
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    agents = httpx.get(f"{BASE}/agents/", headers=h, timeout=30.0).json()
    active = next(a for a in agents if a.get("is_system") and a.get("mode") == "ACTIVE")
    tag = uuid.uuid4().hex[:6]

    camp = httpx.post(
        f"{BASE}/campaigns/",
        headers=h,
        json={
            "name": f"WorkerFix {tag}",
            "agent_id": active["id"],
            "channel_types": ["whatsapp"],
        },
        timeout=30.0,
    ).json()
    cid = camp["id"]

    base = httpx.post(
        f"{BASE}/lead-bases/",
        headers=h,
        json={
            "campaign_id": cid,
            "data_recebimento": str(date.today()),
            "channel_types": ["whatsapp"],
        },
        timeout=30.0,
    ).json()

    httpx.post(
        f"{BASE}/leads/",
        headers=h,
        json={
            "lead_base_id": base["id"],
            "nome_cliente": "WorkerFix Lead",
            "telefone_1": "+5511999887766",
            "aux_values": {},
        },
        timeout=30.0,
    ).raise_for_status()

    start = httpx.post(
        f"{BASE}/campaigns/{cid}/activations/whatsapp/start",
        headers=h,
        timeout=30.0,
    )
    print("start", start.status_code, start.json())

    rows = asyncio.run(poll_interactions(cid))
    for row in rows:
        print(f"LeadInteraction: channel={row.channel_type} status={row.status}")

    httpx.delete(f"{BASE}/campaigns/{cid}", headers=h, timeout=30.0)

    ok = len(rows) >= 1 and all(r.channel_type == "whatsapp" for r in rows)
    print("OK" if ok else "FAIL", f"count={len(rows)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
