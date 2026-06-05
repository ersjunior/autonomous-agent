"""
Aplicação central de tabulação em LeadInteraction.

Gancho SIP (futuro): webhook Twilio StatusCallback / Asterisk chamará
``apply_tabulacao(..., sip_code="SIP:486")`` — não implementado nesta entrega.

Política de QUANDO tabular (integradores devem respeitar):
  - Status terminal (convertido, recusou, nao_atendido, erro*)
  - Intent purchase/cancel (resultado claro)
  - Escalonamento para humano (``escalated=True`` / NEG:ESCALADO) — B-1
  - SIP futuro
  - NÃO tabular em em_andamento sem sinal

  * status erro: regras não mapeiam; IA pode classificar se houver texto indicativo.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.workers.tabulacao_agent import classify_tabulacao
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao
from app.services.tabulacao_mapping import (
    resolve_tabulacao_by_rules,
    resolve_tabulacao_by_sip,
    resolve_tabulacao_for_escalation,
)
from worker.tasks.conversation_routing import TERMINAL_STATUSES
from worker.tasks.lead_tracking import POSITIVE_INTENTS, REFUSAL_INTENTS

logger = logging.getLogger(__name__)

CLASSIFICATION_INTENTS = POSITIVE_INTENTS | REFUSAL_INTENTS

_codigo_id_cache: dict[str, uuid.UUID | None] = {}


def is_classification_moment(
    status_interno: str | None,
    intent: str | None = None,
    *,
    escalated: bool = False,
) -> bool:
    """Momento em que faz sentido atribuir tabulação (terminal, intent claro ou escalonamento)."""
    if escalated:
        return True
    status = (status_interno or "").lower()
    if status in TERMINAL_STATUSES:
        return True
    if intent and intent.lower() in CLASSIFICATION_INTENTS:
        return True
    return False


async def _lookup_tabulacao_id(session: AsyncSession, codigo: str) -> uuid.UUID | None:
    if codigo in _codigo_id_cache:
        return _codigo_id_cache[codigo]

    result = await session.execute(
        select(Tabulacao.id).where(
            Tabulacao.codigo == codigo,
            Tabulacao.is_system.is_(True),
        )
    )
    tab_id = result.scalar_one_or_none()
    _codigo_id_cache[codigo] = tab_id
    return tab_id


async def _catalog_for_owner(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
) -> list[dict[str, str]]:
    result = await session.execute(
        select(Tabulacao).where(
            or_(Tabulacao.is_system.is_(True), Tabulacao.user_id == owner_user_id)
        )
    )
    return [
        {
            "codigo": row.codigo,
            "nome": row.nome,
            "categoria": row.categoria,
        }
        for row in result.scalars().all()
    ]


async def _resolve_owner_user_id(
    session: AsyncSession,
    lead_interaction: LeadInteraction,
) -> uuid.UUID | None:
    if lead_interaction.campaign is not None:
        return lead_interaction.campaign.user_id
    from app.models.campaign import Campaign

    campaign = await session.get(Campaign, lead_interaction.campaign_id)
    return campaign.user_id if campaign else None


async def apply_tabulacao(
    session: AsyncSession,
    lead_interaction: LeadInteraction,
    *,
    intent: str | None = None,
    status_interno: str | None = None,
    channel: str | None = None,
    sip_code: str | None = None,
    origem: str | None = None,
    conversation_text: str | None = None,
    escalated: bool = False,
) -> bool:
    """
    Atribui tabulação ao LeadInteraction se houver match.

    Retorna True se tabulacao_id foi definido.
    """
    status = (status_interno or lead_interaction.status or "").lower()
    ch = channel or lead_interaction.channel_type

    if sip_code is None and not escalated and not is_classification_moment(status, intent):
        return False

    codigo: str | None = None
    tab_origem: str | None = origem

    if escalated:
        codigo = resolve_tabulacao_for_escalation()
        tab_origem = tab_origem or "ESCALATION"
    elif sip_code:
        codigo = resolve_tabulacao_by_sip(sip_code)
        tab_origem = tab_origem or "SIP"
    else:
        codigo = resolve_tabulacao_by_rules(intent, status, ch)
        if codigo:
            tab_origem = tab_origem or "INTENT"

    owner_id: uuid.UUID | None = None
    if codigo is None and is_classification_moment(status, intent):
        owner_id = await _resolve_owner_user_id(session, lead_interaction)
        text = conversation_text or lead_interaction.devolutiva or ""
        if owner_id and text.strip():
            catalog = await _catalog_for_owner(session, owner_id)
            codigo = await classify_tabulacao(text, catalog)
            if codigo:
                tab_origem = "IA"

    if not codigo:
        logger.debug(
            "apply_tabulacao: sem match lead=%s status=%s intent=%s sip=%s",
            lead_interaction.lead_id,
            status,
            intent,
            sip_code,
        )
        return False

    tab_id = await _lookup_tabulacao_id(session, codigo)
    if tab_id is None and owner_id is None:
        owner_id = await _resolve_owner_user_id(session, lead_interaction)
    if tab_id is None and owner_id:
        result = await session.execute(
            select(Tabulacao.id).where(
                Tabulacao.codigo == codigo,
                Tabulacao.user_id == owner_id,
            )
        )
        tab_id = result.scalar_one_or_none()

    if tab_id is None:
        logger.warning("apply_tabulacao: código %s não encontrado no catálogo", codigo)
        return False

    now = datetime.now(timezone.utc)
    lead_interaction.tabulacao_id = tab_id
    lead_interaction.tabulacao_origem = tab_origem
    lead_interaction.tabulacao_aplicada_em = now
    await session.flush()

    logger.info(
        "Tabulação aplicada lead=%s codigo=%s origem=%s",
        lead_interaction.lead_id,
        codigo,
        tab_origem,
    )
    return True


async def maybe_apply_tabulacao_on_transition(
    session: AsyncSession,
    lead_interaction: LeadInteraction,
    *,
    intent: str | None = None,
    status_interno: str | None = None,
    channel: str | None = None,
    conversation_text: str | None = None,
    sip_code: str | None = None,
    escalated: bool = False,
) -> bool:
    """Atalho para integradores: só aplica em momento de classificação."""
    status = status_interno or lead_interaction.status
    if sip_code is None and not escalated and not is_classification_moment(status, intent):
        return False
    return await apply_tabulacao(
        session,
        lead_interaction,
        intent=intent,
        status_interno=status,
        channel=channel,
        sip_code=sip_code,
        conversation_text=conversation_text,
        escalated=escalated,
    )
