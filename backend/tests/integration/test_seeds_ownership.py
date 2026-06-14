"""Integração — idempotência dos seeds + ownership/autorização (is_system, dono, import)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.authorization import (
    IMPORT_LEAD_DELETE_DETAIL,
    IMPORT_LEAD_EDIT_DETAIL,
    SYSTEM_RECORD_DELETE_DETAIL,
    SYSTEM_RECORD_EDIT_DETAIL,
    can_delete,
    can_edit,
    can_edit_lead,
    can_view,
    is_lead_from_import,
    raise_if_cannot_delete,
    raise_if_cannot_edit,
    raise_if_cannot_delete_lead,
    raise_if_cannot_edit_lead,
    raise_if_cannot_view,
)
from app.core.seed import (
    SEED_AGENT_NAMES,
    SEED_CHANNEL_NAMES,
    SEED_TABULACAO_CODIGOS,
    ensure_seed_flags,
    seed_default_admin,
    seed_default_agents,
    seed_default_channels,
    seed_default_tabulacoes,
)
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.channel import Channel, ChannelType
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
from app.models.tabulacao import Tabulacao
from tests.integration.helpers import OwnerContext, create_owner_context, get_admin_user

pytestmark = pytest.mark.integration


async def _count_for_admin(session, model, admin_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(model.user_id == admin_id)
    )


async def _system_tabulacoes(session) -> list[Tabulacao]:
    result = await session.execute(
        select(Tabulacao).where(Tabulacao.is_system.is_(True))
    )
    return list(result.scalars().all())


# --- Parte A: idempotência dos seeds ---


async def test_seed_default_channels_is_idempotent(db_session) -> None:
    await seed_default_admin(db_session)
    admin = await get_admin_user(db_session)

    await seed_default_channels(db_session)
    count_first = await _count_for_admin(db_session, Channel, admin.id)

    await seed_default_channels(db_session)
    count_second = await _count_for_admin(db_session, Channel, admin.id)

    assert count_first == count_second == len(SEED_CHANNEL_NAMES)

    channels = (
        await db_session.execute(select(Channel).where(Channel.user_id == admin.id))
    ).scalars().all()
    names = {ch.name for ch in channels}
    types = {ch.type for ch in channels}

    assert names == set(SEED_CHANNEL_NAMES)
    assert ChannelType.WHATSAPP in types
    assert ChannelType.TELEGRAM in types
    assert ChannelType.VOICE in types
    assert all(ch.is_system for ch in channels)


async def test_seed_default_agents_is_idempotent(db_session) -> None:
    await seed_default_admin(db_session)
    admin = await get_admin_user(db_session)

    await seed_default_agents(db_session)
    count_first = await _count_for_admin(db_session, Agent, admin.id)

    await seed_default_agents(db_session)
    count_second = await _count_for_admin(db_session, Agent, admin.id)

    assert count_first == count_second == len(SEED_AGENT_NAMES)

    agents = (
        await db_session.execute(select(Agent).where(Agent.user_id == admin.id))
    ).scalars().all()
    by_name = {a.name: a for a in agents}

    assert set(by_name) == set(SEED_AGENT_NAMES)
    assert by_name["Agente_Ativo"].mode == AgentMode.ACTIVE
    assert by_name["Agente_Receptivo"].mode == AgentMode.RECEPTIVE
    assert all(a.is_system for a in agents)


async def test_seed_default_tabulacoes_is_idempotent_and_complete(db_session) -> None:
    await seed_default_admin(db_session)

    await seed_default_tabulacoes(db_session)
    first = await _system_tabulacoes(db_session)

    await seed_default_tabulacoes(db_session)
    second = await _system_tabulacoes(db_session)

    assert len(first) == len(second) == len(SEED_TABULACAO_CODIGOS)

    codigos = {t.codigo for t in second}
    assert codigos == set(SEED_TABULACAO_CODIGOS)
    assert any(c.startswith("NEG:") for c in codigos)
    assert any(c.startswith("SIP:") for c in codigos)
    assert all(t.is_system for t in second)


async def test_ensure_seed_flags_is_idempotent(db_session) -> None:
    await seed_default_admin(db_session)
    await seed_default_channels(db_session)
    await seed_default_agents(db_session)
    await seed_default_tabulacoes(db_session)
    admin = await get_admin_user(db_session)

    channel = (
        await db_session.execute(
            select(Channel).where(
                Channel.user_id == admin.id,
                Channel.name == "WhatsApp_Agent",
            )
        )
    ).scalar_one()
    channel.is_system = False
    agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Ativo",
            )
        )
    ).scalar_one()
    agent.is_system = False
    await db_session.flush()

    await ensure_seed_flags(db_session)
    assert channel.is_system is True
    assert agent.is_system is True

    await ensure_seed_flags(db_session)
    assert channel.is_system is True
    assert agent.is_system is True


async def test_full_seed_sequence_requires_admin_first(db_session) -> None:
    """Canais/agentes/tabulacoes dependem do admin; ordem completa deve popular tudo."""
    await seed_default_admin(db_session)
    await seed_default_channels(db_session)
    await seed_default_agents(db_session)
    await seed_default_tabulacoes(db_session)
    await ensure_seed_flags(db_session)

    admin = await get_admin_user(db_session)

    assert await _count_for_admin(db_session, Channel, admin.id) == 3
    assert await _count_for_admin(db_session, Agent, admin.id) == 2
    assert len(await _system_tabulacoes(db_session)) == 16


async def test_seeds_without_admin_are_no_ops(db_session) -> None:
    await seed_default_channels(db_session)
    await seed_default_agents(db_session)
    await seed_default_tabulacoes(db_session)

    assert await db_session.scalar(select(func.count()).select_from(Channel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Agent)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Tabulacao)) == 0


# --- Parte B: ownership / autorização ---


async def test_system_agent_not_editable_or_deletable(system_seeds, db_session) -> None:
    admin = await get_admin_user(db_session)
    agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Ativo",
            )
        )
    ).scalar_one()

    assert agent.is_system is True
    assert can_edit(agent, admin) is False
    assert can_delete(agent, admin) is False

    with pytest.raises(HTTPException) as edit_exc:
        raise_if_cannot_edit(agent, admin)
    assert edit_exc.value.status_code == 403
    assert edit_exc.value.detail == SYSTEM_RECORD_EDIT_DETAIL

    with pytest.raises(HTTPException) as del_exc:
        raise_if_cannot_delete(agent, admin)
    assert del_exc.value.status_code == 403
    assert del_exc.value.detail == SYSTEM_RECORD_DELETE_DETAIL


async def test_system_channel_not_editable(system_seeds, db_session) -> None:
    admin = await get_admin_user(db_session)
    channel = (
        await db_session.execute(
            select(Channel).where(
                Channel.user_id == admin.id,
                Channel.name == "Telegram_Agent",
            )
        )
    ).scalar_one()

    assert can_edit(channel, admin) is False
    with pytest.raises(HTTPException) as exc:
        raise_if_cannot_edit(channel, admin)
    assert exc.value.status_code == 403


async def test_system_campaign_not_editable(db_session, owner_ctx: OwnerContext) -> None:
    campaign = Campaign(
        user_id=owner_ctx.user.id,
        agent_id=owner_ctx.agent.id,
        name="System Campaign",
        status="active",
        is_system=True,
    )
    db_session.add(campaign)
    await db_session.flush()

    assert can_edit(campaign, owner_ctx.user) is False
    with pytest.raises(HTTPException) as exc:
        raise_if_cannot_edit(campaign, owner_ctx.user)
    assert exc.value.status_code == 403
    assert exc.value.detail == SYSTEM_RECORD_EDIT_DETAIL


async def test_owner_can_edit_own_non_system_records(
    owner_ctx: OwnerContext, second_owner, db_session
) -> None:
    assert owner_ctx.agent.is_system is False
    assert can_edit(owner_ctx.agent, owner_ctx.user) is True
    assert can_edit(owner_ctx.agent, second_owner) is False
    assert can_delete(owner_ctx.campaign, owner_ctx.user) is True
    assert can_delete(owner_ctx.campaign, second_owner) is False

    raise_if_cannot_edit(owner_ctx.agent, owner_ctx.user)
    raise_if_cannot_delete(owner_ctx.campaign, owner_ctx.user)

    with pytest.raises(HTTPException) as exc:
        raise_if_cannot_edit(owner_ctx.agent, second_owner)
    assert exc.value.status_code == 404


async def test_is_lead_from_import_is_read_only(
    owner_ctx: OwnerContext, db_session
) -> None:
    imported_base = LeadBase(
        campaign_id=owner_ctx.campaign.id,
        data_recebimento=owner_ctx.lead_base.data_recebimento,
        source=LeadBaseSource.IMPORT,
    )
    db_session.add(imported_base)
    await db_session.flush()

    imported_lead = Lead(
        user_id=owner_ctx.user.id,
        lead_base_id=imported_base.id,
        id_cliente="IMP-001",
        nome_cliente="Lead Importado",
    )
    db_session.add(imported_lead)
    await db_session.flush()
    await db_session.refresh(imported_lead, attribute_names=["lead_base_id"])
    imported_lead.lead_base = imported_base

    assert is_lead_from_import(imported_lead) is True
    assert can_edit(owner_ctx.lead, owner_ctx.user) is True
    assert can_edit_lead(imported_lead, owner_ctx.user) is False

    with pytest.raises(HTTPException) as edit_exc:
        raise_if_cannot_edit_lead(imported_lead, owner_ctx.user)
    assert edit_exc.value.status_code == 403
    assert edit_exc.value.detail == IMPORT_LEAD_EDIT_DETAIL

    with pytest.raises(HTTPException) as del_exc:
        raise_if_cannot_delete_lead(imported_lead, owner_ctx.user)
    assert del_exc.value.status_code == 403
    assert del_exc.value.detail == IMPORT_LEAD_DELETE_DETAIL


async def test_visibility_system_and_owner_scope(
    system_seeds, owner_ctx: OwnerContext, second_owner, db_session
) -> None:
    admin = await get_admin_user(db_session)
    system_agent = (
        await db_session.execute(
            select(Agent).where(
                Agent.user_id == admin.id,
                Agent.name == "Agente_Receptivo",
            )
        )
    ).scalar_one()

    other_ctx = await create_owner_context(db_session, email_suffix="visibility")

    assert can_view(system_agent, owner_ctx.user) is True
    assert can_view(system_agent, second_owner) is True

    assert can_view(owner_ctx.agent, owner_ctx.user) is True
    assert can_view(owner_ctx.agent, second_owner) is False
    assert can_view(other_ctx.agent, other_ctx.user) is True
    assert can_view(other_ctx.agent, owner_ctx.user) is False

    with pytest.raises(HTTPException) as exc:
        raise_if_cannot_view(owner_ctx.agent, second_owner)
    assert exc.value.status_code == 404

    raise_if_cannot_view(system_agent, second_owner)
