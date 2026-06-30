"""Aggregated metrics for the dashboard home page."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.channel import Channel
from app.models.lead import Lead
from app.models.lead_base import LeadBase
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.schemas.dashboard import (
    DashboardCampaignRow,
    DashboardCampaignsResponse,
    DashboardCards,
    DashboardSummaryResponse,
)
from app.services.metrics import (
    _empty_channel_counts,
    _empty_status_counts,
)

_CONTATO_TABULACAO_CODIGOS = ("SIP:200", "NEG:ESCALADO")
_SUCESSO_TABULACAO_CODIGOS = ("NEG:SUCESSO", "NEG:VENDA")
_RECUSA_TABULACAO_CODIGO = "NEG:RECUSADO"


def _campaign_scope(user_id: uuid.UUID):
    """Campanhas visíveis ao usuário (dono ou seed is_system)."""
    return or_(Campaign.is_system.is_(True), Campaign.user_id == user_id)


def _acionado_interaction_exists(channel_type: str | None):
    """
    EXISTS: lead possui interação acionada na campanha da base.

    Acionado = data_acionamento preenchido OU tentativas > 0.
    """
    conditions = [
        LeadInteraction.lead_id == Lead.id,
        LeadInteraction.campaign_id == LeadBase.campaign_id,
        or_(
            LeadInteraction.data_acionamento.isnot(None),
            LeadInteraction.tentativas > 0,
        ),
    ]
    if channel_type is not None:
        conditions.append(LeadInteraction.channel_type == channel_type)
    return exists(select(1).select_from(LeadInteraction).where(*conditions))


def _safe_ratio(numerator: int, denominator: int, *, decimals: int = 2) -> float:
    """Divisão com guarda de zero; conversão/spin como fração 0–1 (frontend formata %)."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, decimals)


def _interaction_filters(campaign_filter, channel_type: str | None):
    filters = [campaign_filter]
    if channel_type is not None:
        filters.append(LeadInteraction.channel_type == channel_type)
    return filters


def _filled_string_point(column):
    """1 se coluna string não-nula e não-vazia após trim; senão 0."""
    trimmed = func.trim(column)
    return case(
        (and_(column.isnot(None), trimmed != ""), 1),
        else_=0,
    )


def _telegram_id_point():
    """1 se aux_values.telegram_id presente e não-vazio."""
    telegram_id = Lead.aux_values["telegram_id"].as_string()
    return case(
        (and_(telegram_id.isnot(None), telegram_id != ""), 1),
        else_=0,
    )


def _lead_contact_points_expr():
    """Pontos de contato acionáveis por lead (telefones, email, telegram_id)."""
    return (
        _filled_string_point(Lead.telefone_1)
        + _filled_string_point(Lead.telefone_2)
        + _filled_string_point(Lead.telefone_3)
        + _filled_string_point(Lead.email_cliente)
        + _telegram_id_point()
    )


def _contato_predicate():
    return or_(
        LeadInteraction.data_ultimo_contato.isnot(None),
        Tabulacao.codigo.in_(_CONTATO_TABULACAO_CODIGOS),
    )


def _sucesso_predicate():
    return or_(
        Tabulacao.codigo.in_(_SUCESSO_TABULACAO_CODIGOS),
        and_(
            LeadInteraction.tabulacao_id.is_(None),
            LeadInteraction.status == "convertido",
        ),
    )


def _recusa_predicate():
    return or_(
        Tabulacao.codigo == _RECUSA_TABULACAO_CODIGO,
        and_(
            LeadInteraction.tabulacao_id.is_(None),
            LeadInteraction.status == "recusou",
        ),
    )


async def get_dashboard_campaigns(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel_type: str | None = None,
) -> DashboardCampaignsResponse:
    """
    Uma linha por campanha visível ao usuário.

    Estratégia (sem N+1):
      Q1 — campanhas (id, name)
      Q2 — leads + datas via lead_bases (GROUP BY campaign_id)
      Q3 — SUM(acionáveis) por campanha (pontos de contato nos leads)
      Q4 — SUM(tentativas) por campanha
      Q5 — COUNT(lead_interactions.id) contato por campanha (ocorrências)
      Q6 — COUNT(lead_interactions.id) sucesso por campanha (ocorrências)
      Q7 — COUNT(lead_interactions.id) recusa por campanha (ocorrências)
    Merge em Python; cpc = sucesso + recusa; spin/conversao calculados aqui.
    """
    campaign_filter = _campaign_scope(user_id)
    interaction_filters = _interaction_filters(campaign_filter, channel_type)

    campaign_rows = list(
        (
            await db.execute(
                select(Campaign.id, Campaign.name)
                .where(campaign_filter)
                .order_by(Campaign.name)
            )
        ).all()
    )

    rows_by_id: dict[uuid.UUID, dict] = {
        campaign_id: {
            "campaign_name": name,
            "leads": 0,
            "acionaveis": 0,
            "data_recebimento": None,
            "data_inicio": None,
            "data_fim": None,
            "tentativas": 0,
            "contato": 0,
            "sucesso": 0,
            "recusa": 0,
        }
        for campaign_id, name in campaign_rows
    }

    if not rows_by_id:
        return DashboardCampaignsResponse(campaigns=[])

    lead_stats = await db.execute(
        select(
            LeadBase.campaign_id,
            func.count(func.distinct(Lead.id)),
            func.min(LeadBase.data_recebimento),
            func.min(LeadBase.data_inicio),
            func.max(LeadBase.data_fim),
        )
        .select_from(LeadBase)
        .outerjoin(Lead, Lead.lead_base_id == LeadBase.id)
        .join(Campaign, LeadBase.campaign_id == Campaign.id)
        .where(campaign_filter)
        .group_by(LeadBase.campaign_id)
    )
    for campaign_id, lead_count, recv, inicio, fim in lead_stats.all():
        bucket = rows_by_id.get(campaign_id)
        if bucket is None:
            continue
        bucket["leads"] = int(lead_count or 0)
        bucket["data_recebimento"] = recv
        bucket["data_inicio"] = inicio
        bucket["data_fim"] = fim

    acionaveis_rows = await db.execute(
        select(LeadBase.campaign_id, func.sum(_lead_contact_points_expr()))
        .select_from(LeadBase)
        .join(Lead, Lead.lead_base_id == LeadBase.id)
        .join(Campaign, LeadBase.campaign_id == Campaign.id)
        .where(campaign_filter)
        .group_by(LeadBase.campaign_id)
    )
    for campaign_id, total in acionaveis_rows.all():
        bucket = rows_by_id.get(campaign_id)
        if bucket is None:
            continue
        bucket["acionaveis"] = int(total or 0)

    tentativas_rows = await db.execute(
        select(LeadInteraction.campaign_id, func.sum(LeadInteraction.tentativas))
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(*interaction_filters)
        .group_by(LeadInteraction.campaign_id)
    )
    for campaign_id, total in tentativas_rows.all():
        bucket = rows_by_id.get(campaign_id)
        if bucket is None:
            continue
        bucket["tentativas"] = int(total or 0)

    contato_rows = await db.execute(
        select(LeadInteraction.campaign_id, func.count(LeadInteraction.id))
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .outerjoin(Tabulacao, LeadInteraction.tabulacao_id == Tabulacao.id)
        .where(*interaction_filters, _contato_predicate())
        .group_by(LeadInteraction.campaign_id)
    )
    for campaign_id, total in contato_rows.all():
        bucket = rows_by_id.get(campaign_id)
        if bucket is None:
            continue
        bucket["contato"] = int(total or 0)

    sucesso_rows = await db.execute(
        select(LeadInteraction.campaign_id, func.count(LeadInteraction.id))
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .outerjoin(Tabulacao, LeadInteraction.tabulacao_id == Tabulacao.id)
        .where(*interaction_filters, _sucesso_predicate())
        .group_by(LeadInteraction.campaign_id)
    )
    for campaign_id, total in sucesso_rows.all():
        bucket = rows_by_id.get(campaign_id)
        if bucket is None:
            continue
        bucket["sucesso"] = int(total or 0)

    recusa_rows = await db.execute(
        select(LeadInteraction.campaign_id, func.count(LeadInteraction.id))
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .outerjoin(Tabulacao, LeadInteraction.tabulacao_id == Tabulacao.id)
        .where(*interaction_filters, _recusa_predicate())
        .group_by(LeadInteraction.campaign_id)
    )
    for campaign_id, total in recusa_rows.all():
        bucket = rows_by_id.get(campaign_id)
        if bucket is None:
            continue
        bucket["recusa"] = int(total or 0)

    campaigns_out: list[DashboardCampaignRow] = []
    for campaign_id, name in campaign_rows:
        data = rows_by_id[campaign_id]
        tentativas = data["tentativas"]
        acionaveis = data["acionaveis"]
        sucesso = data["sucesso"]
        recusa = data["recusa"]
        cpc = sucesso + recusa
        campaigns_out.append(
            DashboardCampaignRow(
                campaign_id=campaign_id,
                campaign_name=data["campaign_name"],
                leads=data["leads"],
                acionaveis=acionaveis,
                data_recebimento=data["data_recebimento"],
                data_inicio=data["data_inicio"],
                data_fim=data["data_fim"],
                tentativas=tentativas,
                spin=_safe_ratio(tentativas, acionaveis),
                contato=data["contato"],
                cpc=cpc,
                recusa=recusa,
                sucesso=sucesso,
                conversao=_safe_ratio(sucesso, cpc),
            )
        )

    return DashboardCampaignsResponse(campaigns=campaigns_out)


async def get_dashboard_summary(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel_type: str | None = None,
) -> DashboardSummaryResponse:
    campaign_filter = _campaign_scope(user_id)

    # Cards — mesmo critério das rotas GET /agents/, /channels/, /leads/, /campaigns/.
    agents = (
        await db.scalar(
            select(func.count())
            .select_from(Agent)
            .where(or_(Agent.is_system.is_(True), Agent.user_id == user_id))
        )
        or 0
    )

    active_channels = (
        await db.scalar(
            select(func.count())
            .select_from(Channel)
            .where(
                or_(Channel.is_system.is_(True), Channel.user_id == user_id),
                Channel.is_active.is_(True),
            )
        )
        or 0
    )

    leads = (
        await db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(or_(Lead.is_system.is_(True), Lead.user_id == user_id))
        )
        or 0
    )

    active_campaigns = (
        await db.scalar(
            select(func.count())
            .select_from(Campaign)
            .where(campaign_filter, Campaign.status == "active")
        )
        or 0
    )

    # Leads únicos nas campanhas do usuário (via lead_base → campaign).
    total_leads_in_campaigns = (
        await db.scalar(
            select(func.count(Lead.id))
            .select_from(Lead)
            .join(LeadBase, Lead.lead_base_id == LeadBase.id)
            .join(Campaign, LeadBase.campaign_id == Campaign.id)
            .where(campaign_filter)
        )
        or 0
    )

    leads_acionados = (
        await db.scalar(
            select(func.count(Lead.id))
            .select_from(Lead)
            .join(LeadBase, Lead.lead_base_id == LeadBase.id)
            .join(Campaign, LeadBase.campaign_id == Campaign.id)
            .where(campaign_filter, _acionado_interaction_exists(channel_type))
        )
        or 0
    )

    leads_virgens = max(total_leads_in_campaigns - leads_acionados, 0)

    # tentativas_por_canal — SUM(LeadInteraction.tentativas), não COUNT de linhas.
    channel_sum_stmt = (
        select(LeadInteraction.channel_type, func.sum(LeadInteraction.tentativas))
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(campaign_filter)
        .group_by(LeadInteraction.channel_type)
    )
    if channel_type is not None:
        channel_sum_stmt = channel_sum_stmt.where(
            LeadInteraction.channel_type == channel_type
        )

    channel_rows = list((await db.execute(channel_sum_stmt)).all())
    if channel_type is not None:
        tentativas_por_canal = {channel_type: 0}
        for ch, total in channel_rows:
            if (ch or "").lower() == channel_type:
                tentativas_por_canal[channel_type] = int(total or 0)
    else:
        tentativas_por_canal = _empty_channel_counts()
        for ch, total in channel_rows:
            key = (ch or "").lower()
            if key in tentativas_por_canal:
                tentativas_por_canal[key] = int(total or 0)

    # tentativas_por_status — COUNT(interações) por status (empilhamento no gráfico).
    status_count_stmt = (
        select(LeadInteraction.status, func.count())
        .select_from(LeadInteraction)
        .join(Campaign, LeadInteraction.campaign_id == Campaign.id)
        .where(campaign_filter)
        .group_by(LeadInteraction.status)
    )
    if channel_type is not None:
        status_count_stmt = status_count_stmt.where(
            LeadInteraction.channel_type == channel_type
        )

    status_rows = list((await db.execute(status_count_stmt)).all())
    tentativas_por_status = _empty_status_counts()
    for status, count in status_rows:
        key = (status or "").lower()
        if key in tentativas_por_status:
            tentativas_por_status[key] = int(count)

    return DashboardSummaryResponse(
        cards=DashboardCards(
            agents=int(agents),
            active_channels=int(active_channels),
            leads=int(leads),
            active_campaigns=int(active_campaigns),
        ),
        leads_acionados=int(leads_acionados),
        leads_virgens=int(leads_virgens),
        tentativas_por_canal=tentativas_por_canal,
        tentativas_por_status=tentativas_por_status,
    )
