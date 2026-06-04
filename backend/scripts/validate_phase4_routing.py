"""Validação Fase 4 — roteamento ACTIVE/RECEPTIVE (executar no container backend)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from worker.tasks.conversation_routing import (
    SEED_AGENT_ACTIVE_NAME,
    SEED_AGENT_RECEPTIVE_NAME,
    is_active_conversation_open,
    resolve_inbound_agent,
)
from worker.tasks.outbound_campaign import _send_campaign_message


async def _get_seed_agents(session):
    r = await session.execute(
        select(Agent).where(
            Agent.is_system.is_(True),
            Agent.name.in_([SEED_AGENT_ACTIVE_NAME, SEED_AGENT_RECEPTIVE_NAME]),
        )
    )
    agents = {a.name: a for a in r.scalars().all()}
    return agents


async def main() -> None:
    results: list[str] = []

    async with AsyncSessionLocal() as session:
        agents = await _get_seed_agents(session)
        results.append(
            f"Seed agents: Ativo={agents.get(SEED_AGENT_ACTIVE_NAME) is not None} "
            f"Receptivo={agents.get(SEED_AGENT_RECEPTIVE_NAME) is not None}"
        )

        # A — sem lead
        a_agent = await resolve_inbound_agent(session, None, "whatsapp")
        results.append(
            f"A primeiro contato (lead=None): {a_agent.name} mode={a_agent.mode.value} "
            f"OK={a_agent.name == SEED_AGENT_RECEPTIVE_NAME}"
        )

        # Precisa de lead + campanha para B–E
        camp = await session.scalar(
            select(Campaign)
            .options(selectinload(Campaign.agent))
            .join(LeadBase)
            .limit(1)
        )
        if camp is None:
            results.append("B–E SKIP: nenhuma campanha no banco")
            for line in results:
                print(line)
            return

        lead = await session.scalar(
            select(Lead).where(Lead.lead_base_id.in_(
                select(LeadBase.id).where(LeadBase.campaign_id == camp.id)
            )).limit(1)
        )
        if lead is None:
            lead = Lead(
                user_id=camp.user_id,
                lead_base_id=(await session.scalar(
                    select(LeadBase.id).where(LeadBase.campaign_id == camp.id).limit(1)
                )),
                nome_cliente="Routing Test Lead",
                telefone_1="5511999887766",
            )
            session.add(lead)
            await session.flush()

        now = datetime.now(timezone.utc)

        # B — conversa aberta
        li_b = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="acionado",
            data_acionamento=now,
            data_ultimo_contato=now,
        )
        session.add(li_b)
        await session.flush()
        b_agent = await resolve_inbound_agent(session, lead, "whatsapp")
        open_ok = is_active_conversation_open(li_b)
        results.append(
            f"B após outbound (acionado): open={open_ok} agent={b_agent.name} "
            f"mode={b_agent.mode.value} OK={b_agent.mode == AgentMode.ACTIVE}"
        )
        await session.delete(li_b)
        await session.flush()

        # C — terminal convertido
        li_c = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="convertido",
            data_acionamento=now - timedelta(hours=1),
            data_ultimo_contato=now,
        )
        session.add(li_c)
        await session.flush()
        c_agent = await resolve_inbound_agent(session, lead, "whatsapp")
        results.append(
            f"C status terminal convertido: agent={c_agent.name} mode={c_agent.mode.value} "
            f"OK={c_agent.mode == AgentMode.RECEPTIVE}"
        )
        await session.delete(li_c)
        await session.flush()

        # D — inatividade
        old = now - timedelta(hours=settings.active_conversation_timeout_hours + 1)
        li_d = LeadInteraction(
            lead_id=lead.id,
            campaign_id=camp.id,
            channel_type="whatsapp",
            status="acionado",
            data_acionamento=old,
            data_ultimo_contato=old,
        )
        session.add(li_d)
        await session.flush()
        d_agent = await resolve_inbound_agent(session, lead, "whatsapp")
        results.append(
            f"D inatividade (>{settings.active_conversation_timeout_hours}h): "
            f"open={is_active_conversation_open(li_d)} agent={d_agent.name} "
            f"OK={d_agent.mode == AgentMode.RECEPTIVE}"
        )
        await session.delete(li_d)
        await session.commit()

    # E — outbound RECEPTIVE (nova sessão)
    async with AsyncSessionLocal() as session:
        receptive = await session.scalar(
            select(Agent).where(Agent.name == SEED_AGENT_RECEPTIVE_NAME, Agent.is_system.is_(True))
        )
        active = await session.scalar(
            select(Agent).where(Agent.name == SEED_AGENT_ACTIVE_NAME, Agent.is_system.is_(True))
        )
        if not receptive or not active:
            results.append("E SKIP: seed agents missing")
        else:
            camp_e = Campaign(
                user_id=receptive.user_id,
                agent_id=receptive.id,
                name="Phase4 Receptive Outbound Test",
                status="draft",
            )
            session.add(camp_e)
            await session.flush()
            lb = LeadBase(
                campaign_id=camp_e.id,
                data_recebimento=now.date(),
                column_mapping={},
            )
            session.add(lb)
            await session.flush()
            from app.models.lead_base import LeadBaseChannel

            session.add(LeadBaseChannel(lead_base_id=lb.id, channel_type="whatsapp"))
            lead_e = Lead(
                user_id=receptive.user_id,
                lead_base_id=lb.id,
                nome_cliente="Outbound Block Test",
                telefone_1="5511888777666",
            )
            session.add(lead_e)
            await session.commit()

            out = await _send_campaign_message(str(lead_e.id), str(camp_e.id))
            results.append(
                f"E outbound campanha RECEPTIVE: blocked={out.get('blocked')} "
                f"reason={out.get('reason')} channels={len(out.get('channels', []))} "
                f"OK={out.get('blocked') is True and len(out.get('channels', [])) == 0}"
            )

            async with AsyncSessionLocal() as s2:
                li = await s2.scalar(
                    select(LeadInteraction).where(
                        LeadInteraction.lead_id == lead_e.id,
                        LeadInteraction.campaign_id == camp_e.id,
                    )
                )
                if li:
                    results.append(f"E tracking devolutiva: {li.devolutiva[:80]}... status={li.status}")

            await session.delete(lead_e)
            await session.delete(lb)
            await session.delete(camp_e)
            await session.commit()

    for line in results:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
