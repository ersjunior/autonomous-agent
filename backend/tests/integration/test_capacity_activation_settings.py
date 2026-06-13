"""Integração — capacidade observada, activation merge e settings (DB + Redis)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.activation_defaults import default_params_for_channel
from app.core.config import settings
from app.models.agent_channel_settings import AgentChannelSettings
from app.models.app_setting import AppSetting
from app.models.lead_interaction import LeadInteraction
from app.models.queue_entry import QueueEntry, QueueEntryStatus
from app.services.activation_service import (
    get_pending_leads_for_channel,
    merged_params,
)
from app.services.capacity_analysis import (
    _observed_aht_seconds,
    _observed_arrival_rate_per_hour,
    get_capacity_analysis,
)
from app.services.capacity_estimate import CapacityEstimate, ResourceSnapshot
from app.services.settings_service import (
    get_redis_settings_version,
    load_into_settings,
    seed_missing_settings,
    update_settings,
)
from tests.integration.helpers import (
    OwnerContext,
    add_campaign_channel,
    add_lead_base_channel,
    create_lead_on_base,
    create_lead_interaction,
)

pytestmark = pytest.mark.integration

BASE = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)


def _fake_resources() -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu_cores=4.0,
        cpu_percent_used=25.0,
        cpu_available_ratio=0.75,
        ram_total_mb=8192.0,
        ram_available_mb=4096.0,
        gpu_signal_available=False,
        gpu_signal_source=None,
        gpu_device_name=None,
        container_estimate=True,
    )


def _fake_estimate(_resources=None) -> CapacityEstimate:
    return CapacityEstimate(
        resource_units_budget=100.0,
        max_weighted_capacity=10,
        channels_if_single_family={"whatsapp": 10},
        channel_costs={"whatsapp": 1.0},
        notes=["test"],
    )


@pytest.fixture
def mock_psutil(monkeypatch):
    """Hardware fixo — foco nas queries observadas do banco."""
    monkeypatch.setattr(
        "app.services.capacity_analysis.read_resources",
        lambda: _fake_resources(),
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.estimate_capacity",
        lambda resources=None: _fake_estimate(resources),
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.resolve_max_weighted_capacity",
        lambda: 10,
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.current_global_usage",
        lambda: 0,
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.current_outbound_bound_weight",
        lambda: 0,
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.current_receptive_bound_weight",
        lambda: 0,
    )


@pytest.mark.asyncio
async def test_observed_arrival_rate_from_queue_entries(
    db_session, mock_psutil, monkeypatch
):
    """48 QueueEntry em 1 dia → λ = 2.0/h."""
    monkeypatch.setattr(settings, "capacity_history_days", 1)
    now = datetime.now(timezone.utc)
    for i in range(48):
        db_session.add(
            QueueEntry(
                channel_type="whatsapp",
                user_id=f"user-{i}",
                enqueued_at=now - timedelta(hours=i % 24),
                status=QueueEntryStatus.WAITING,
            )
        )
    await db_session.flush()

    rate, count = await _observed_arrival_rate_per_hour(db_session, 1)

    assert count == 48
    assert rate == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_observed_aht_from_terminal_interactions(
    db_session, owner_ctx: OwnerContext, mock_psutil, monkeypatch
):
    """3 LI terminais com span de 600s → AHT observado = 600."""
    monkeypatch.setattr(settings, "capacity_history_days", 7)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=2)
    end = start + timedelta(seconds=600)
    for i in range(3):
        li = LeadInteraction(
            lead_id=owner_ctx.lead.id,
            campaign_id=owner_ctx.campaign.id,
            channel_type="whatsapp",
            status="convertido",
            tentativas=1,
            data_acionamento=start + timedelta(minutes=i),
            data_ultimo_contato=end + timedelta(minutes=i),
            created_at=start + timedelta(minutes=i),
        )
        db_session.add(li)
    await db_session.flush()

    aht, samples, source = await _observed_aht_seconds(db_session, 7)

    assert samples == 3
    assert source == "lead_interaction_terminal_span"
    assert aht == pytest.approx(600.0, rel=0.01)


@pytest.mark.asyncio
async def test_get_capacity_analysis_uses_observed_metrics(
    db_session, owner_ctx: OwnerContext, mock_psutil, monkeypatch
):
    """get_capacity_analysis expõe métricas observadas seedadas."""
    monkeypatch.setattr(settings, "capacity_history_days", 1)
    now = datetime.now(timezone.utc)
    db_session.add(
        QueueEntry(
            channel_type="whatsapp",
            user_id="cap-user",
            enqueued_at=now - timedelta(hours=1),
            status=QueueEntryStatus.ANSWERED,
        )
    )
    start = now - timedelta(hours=2)
    for i in range(3):
        db_session.add(
            LeadInteraction(
                lead_id=owner_ctx.lead.id,
                campaign_id=owner_ctx.campaign.id,
                channel_type="whatsapp",
                status="convertido",
                tentativas=1,
                data_acionamento=start + timedelta(minutes=i),
                data_ultimo_contato=start + timedelta(minutes=i, seconds=600),
                created_at=start + timedelta(minutes=i),
            )
        )
    await db_session.flush()

    response = await get_capacity_analysis(db_session)

    assert response.observed.arrival_count >= 1
    assert response.observed.aht_sample_count >= 3
    assert response.observed.aht_source == "lead_interaction_terminal_span"
    assert response.resources.cpu_cores == 4.0


def test_merged_params_precedence():
    """Defaults + override armazenado → merge com precedência do stored."""
    defaults = default_params_for_channel("whatsapp")
    stored = {"chats_simultaneos": 99, "horario_inicio": "10:00"}
    merged = merged_params("whatsapp", stored)

    assert merged["chats_simultaneos"] == 99
    assert merged["horario_inicio"] == "10:00"
    assert merged["horario_fim"] == defaults["horario_fim"]


@pytest.mark.asyncio
async def test_pending_leads_excludes_activated(
    owner_ctx: OwnerContext, db_session
):
    """Leads com canal na base e sem LI → pendentes; com LI → excluído."""
    await add_campaign_channel(db_session, owner_ctx.campaign.id, "whatsapp")
    await add_lead_base_channel(db_session, owner_ctx.lead_base.id, "whatsapp")

    pending_before = await get_pending_leads_for_channel(
        db_session, owner_ctx.campaign.id, "whatsapp", user_id=owner_ctx.user.id
    )
    pending_ids = {lead.id for lead in pending_before}
    assert owner_ctx.lead.id in pending_ids

    other = await create_lead_on_base(
        db_session, owner_ctx, suffix="pending", telefone="5511888777001"
    )
    pending_after = await get_pending_leads_for_channel(
        db_session, owner_ctx.campaign.id, "whatsapp", user_id=owner_ctx.user.id
    )
    assert other.id in {lead.id for lead in pending_after}

    await create_lead_interaction(
        db_session,
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        data_acionamento=BASE,
    )
    pending_final = await get_pending_leads_for_channel(
        db_session, owner_ctx.campaign.id, "whatsapp", user_id=owner_ctx.user.id
    )
    final_ids = {lead.id for lead in pending_final}
    assert owner_ctx.lead.id not in final_ids
    assert other.id in final_ids


@pytest.mark.asyncio
async def test_agent_channel_settings_merge_in_db(
    owner_ctx: OwnerContext, db_session
):
    """Override persistido via AgentChannelSettings reflete no merged_params."""
    row = AgentChannelSettings(
        agent_id=owner_ctx.agent.id,
        channel_type="whatsapp",
        params={"tentativas_sem_resposta": 5},
    )
    db_session.add(row)
    await db_session.flush()

    from app.services.activation_service import get_agent_channel_settings_row

    stored_row = await get_agent_channel_settings_row(
        db_session, owner_ctx.agent.id, "whatsapp"
    )
    params = merged_params("whatsapp", stored_row.params if stored_row else None)

    assert params["tentativas_sem_resposta"] == 5
    assert params["chats_simultaneos"] == default_params_for_channel("whatsapp")[
        "chats_simultaneos"
    ]


@pytest.mark.asyncio
async def test_update_settings_persists_db_and_bumps_redis_version(
    db_session, clean_redis, monkeypatch
):
    """update_settings → AppSetting no banco + settings_version incrementado."""
    monkeypatch.setattr(
        "app.services.settings_sync.mark_local_version",
        lambda _v: None,
    )
    version_before = get_redis_settings_version()

    await update_settings(db_session, {"rag_top_k": 9})

    row = (
        await db_session.execute(
            select(AppSetting).where(
                AppSetting.scope == "global",
                AppSetting.user_id.is_(None),
                AppSetting.key == "rag_top_k",
            )
        )
    ).scalar_one()
    assert row.value == "9"
    assert settings.rag_top_k == 9
    assert get_redis_settings_version() == version_before + 1


@pytest.mark.asyncio
async def test_load_into_settings_reads_persisted_values(
    db_session, clean_redis, monkeypatch
):
    """load_into_settings sobrescreve o singleton a partir do banco."""
    monkeypatch.setattr(
        "app.services.settings_sync.mark_local_version",
        lambda _v: None,
    )
    await update_settings(db_session, {"rag_top_k": 11})
    settings.rag_top_k = 3

    await load_into_settings(db_session)

    assert settings.rag_top_k == 11


@pytest.mark.asyncio
async def test_seed_missing_settings_is_idempotent(db_session, clean_redis):
    """Segunda chamada de seed_missing_settings não insere duplicatas."""
    first = await seed_missing_settings(db_session)
    count_after_first = (
        await db_session.execute(
            select(func.count()).select_from(AppSetting).where(
                AppSetting.scope == "global",
                AppSetting.user_id.is_(None),
            )
        )
    ).scalar_one()

    second = await seed_missing_settings(db_session)

    count_after_second = (
        await db_session.execute(
            select(func.count()).select_from(AppSetting).where(
                AppSetting.scope == "global",
                AppSetting.user_id.is_(None),
            )
        )
    ).scalar_one()

    assert second == 0
    assert count_after_second == count_after_first
