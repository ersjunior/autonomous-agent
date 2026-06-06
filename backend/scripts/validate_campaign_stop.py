"""Validation for POST /campaigns/{id}/stop (run inside backend container)."""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.agent_activation import AgentActivation
from app.models.campaign import Campaign, CampaignChannel
from app.models.user import User
from worker.tasks.activation_scheduler import _process_active_activations_async

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"


async def activations_for_campaign(campaign_id: str) -> list[AgentActivation]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentActivation).where(AgentActivation.campaign_id == uuid.UUID(campaign_id))
        )
        return list(result.scalars().all())


async def campaign_status(campaign_id: str) -> str | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(Campaign, uuid.UUID(campaign_id))
        return row.status if row else None


async def scheduler_includes_campaign(campaign_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentActivation).where(
                AgentActivation.campaign_id == uuid.UUID(campaign_id),
                AgentActivation.is_running.is_(True),
            )
        )
        return result.scalars().first() is not None


async def seed_system_campaign(agent_id: str) -> str | None:
    async with AsyncSessionLocal() as db:
        admin = (
            await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        ).scalar_one_or_none()
        if admin is None:
            return None
        existing = (
            await db.execute(
                select(Campaign).where(
                    Campaign.is_system.is_(True),
                    Campaign.name == "Validação Stop Sistema",
                )
            )
        ).scalar_one_or_none()
        if existing:
            return str(existing.id)
        camp = Campaign(
            user_id=admin.id,
            agent_id=uuid.UUID(agent_id),
            name="Validação Stop Sistema",
            status="active",
            is_system=True,
        )
        db.add(camp)
        await db.flush()
        db.add(CampaignChannel(campaign_id=camp.id, channel_type="whatsapp"))
        await db.commit()
        return str(camp.id)


async def run_validation() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    camp_id: str | None = None
    draft_id: str | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        r_login = await client.post(
            f"{BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        r_login.raise_for_status()
        h = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

        agents = (await client.get(f"{BASE}/agents/", headers=h)).json()
        system_active = next(
            (a for a in agents if a.get("is_system") and a.get("mode") == "ACTIVE"),
            None,
        )
        custom_active = next(
            (a for a in agents if not a.get("is_system") and a.get("mode") == "ACTIVE"),
            None,
        )
        if custom_active is None:
            r_agent = await client.post(
                f"{BASE}/agents/",
                headers=h,
                json={
                    "name": f"Teste Stop {uuid.uuid4().hex[:8]}",
                    "mode": "ACTIVE",
                    "description": "validação stop campaign",
                    "config": {},
                },
            )
            r_agent.raise_for_status()
            custom_active = r_agent.json()

        if system_active:
            system_camp_id = await seed_system_campaign(system_active["id"])
            if system_camp_id:
                r_get_sys = await client.get(f"{BASE}/campaigns/{system_camp_id}", headers=h)
                sys_body = r_get_sys.json()
                results.append(
                    (
                        "GET campanha is_system inclui is_system=true",
                        r_get_sys.status_code == 200 and sys_body.get("is_system") is True,
                        f"status={r_get_sys.status_code} is_system={sys_body.get('is_system')}",
                    )
                )
                r_stop_sys = await client.post(
                    f"{BASE}/campaigns/{system_camp_id}/stop", headers=h
                )
                results.append(
                    (
                        "POST stop campanha is_system → 403",
                        r_stop_sys.status_code == 403,
                        f"status={r_stop_sys.status_code} body={r_stop_sys.text[:120]}",
                    )
                )

        r_draft = await client.post(
            f"{BASE}/campaigns/",
            headers=h,
            json={
                "name": f"Draft Stop {uuid.uuid4().hex[:8]}",
                "agent_id": custom_active["id"],
                "channel_types": ["whatsapp", "telegram"],
            },
        )
        r_draft.raise_for_status()
        draft = r_draft.json()
        draft_id = draft["id"]
        results.append(
            (
                "POST create campanha draft + is_system=false na resposta",
                draft.get("status") == "draft" and draft.get("is_system") is False,
                f"status={draft.get('status')} is_system={draft.get('is_system')}",
            )
        )

        r_stop_draft = await client.post(f"{BASE}/campaigns/{draft_id}/stop", headers=h)
        results.append(
            (
                "POST stop campanha draft → 400",
                r_stop_draft.status_code == 400,
                f"status={r_stop_draft.status_code} body={r_stop_draft.text[:120]}",
            )
        )

        r_create = await client.post(
            f"{BASE}/campaigns/",
            headers=h,
            json={
                "name": f"Cycle Stop {uuid.uuid4().hex[:8]}",
                "agent_id": custom_active["id"],
                "channel_types": ["whatsapp", "telegram"],
            },
        )
        r_create.raise_for_status()
        camp = r_create.json()
        camp_id = camp["id"]
        channel_count = len(camp.get("channel_types", []))

        r_start = await client.post(f"{BASE}/campaigns/{camp_id}/start", headers=h)
        r_start.raise_for_status()
        start_body = r_start.json()
        results.append(
            ("POST start → started", start_body.get("status") == "started", str(start_body))
        )
        status = await campaign_status(camp_id)
        acts = await activations_for_campaign(camp_id)
        results.append(
            (
                "DB após start: status=active + is_running=True",
                status == "active" and bool(acts) and all(a.is_running for a in acts),
                f"db_status={status} activations={[(a.channel_type, a.is_running) for a in acts]}",
            )
        )

        r_stop = await client.post(f"{BASE}/campaigns/{camp_id}/stop", headers=h)
        r_stop.raise_for_status()
        stop_body = r_stop.json()
        results.append(
            (
                "POST stop → paused + activations_stopped",
                stop_body.get("status") == "paused"
                and stop_body.get("activations_stopped") == channel_count,
                str(stop_body),
            )
        )
        status = await campaign_status(camp_id)
        acts = await activations_for_campaign(camp_id)
        scheduler_has = await scheduler_includes_campaign(camp_id)
        sched_stats = await _process_active_activations_async()
        sched_includes = any(camp_id in k for k in sched_stats.get("by_channel", {}))
        results.append(
            (
                "DB após stop: status=paused + is_running=False",
                status == "paused" and bool(acts) and all(not a.is_running for a in acts),
                f"db_status={status} activations={[(a.channel_type, a.is_running) for a in acts]}",
            )
        )
        results.append(
            (
                "Scheduler não inclui campanha parada",
                not scheduler_has and not sched_includes,
                f"scheduler_has_running={scheduler_has} sched_includes={sched_includes}",
            )
        )

        r_restart = await client.post(f"{BASE}/campaigns/{camp_id}/start", headers=h)
        r_restart.raise_for_status()
        restart_body = r_restart.json()
        results.append(
            (
                "POST restart após pause → started",
                restart_body.get("status") == "started",
                str(restart_body),
            )
        )
        status = await campaign_status(camp_id)
        acts = await activations_for_campaign(camp_id)
        results.append(
            (
                "DB após restart: status=active + is_running=True",
                status == "active" and bool(acts) and all(a.is_running for a in acts),
                f"db_status={status} activations={[(a.channel_type, a.is_running) for a in acts]}",
            )
        )

        await client.delete(f"{BASE}/campaigns/{camp_id}", headers=h)
        await client.delete(f"{BASE}/campaigns/{draft_id}", headers=h)

    return results


def main() -> int:
    try:
        results = asyncio.run(run_validation())
    except Exception as exc:
        results = [("Execução geral", False, str(exc))]

    print("\n=== Validação stop_campaign ===\n")
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
