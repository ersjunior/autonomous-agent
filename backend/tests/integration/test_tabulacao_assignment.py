"""Integração — apply_tabulacao e atribuição híbrida (regras → SIP → IA / escalation)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio

from app.core.security import hash_password
from app.core.seed import seed_default_admin, seed_default_tabulacoes
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.lead_base import LeadBase, LeadBaseSource
from app.models.lead_interaction import LeadInteraction
from app.models.tabulacao import Tabulacao, TabulacaoCategoria
from app.models.user import User
from app.services.tabulacao_assignment import (
    apply_tabulacao,
    maybe_apply_tabulacao_on_transition,
)

pytestmark = pytest.mark.integration


@dataclass
class OwnerContext:
    user: User
    agent: Agent
    campaign: Campaign
    lead_base: LeadBase
    lead: Lead


async def _codigo_for(session, lead_interaction: LeadInteraction) -> str | None:
    await session.refresh(lead_interaction, attribute_names=["tabulacao_id"])
    if lead_interaction.tabulacao_id is None:
        return None
    tab = await session.get(Tabulacao, lead_interaction.tabulacao_id)
    return tab.codigo if tab else None


@pytest_asyncio.fixture
async def seeded_catalog(db_session):
    """Admin + catálogo system NEG:* / SIP:* (seed idempotente)."""
    await seed_default_admin(db_session)
    await seed_default_tabulacoes(db_session)
    return db_session


@pytest_asyncio.fixture
async def owner_ctx(seeded_catalog, db_session) -> OwnerContext:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"tab-{suffix}@example.com",
        hashed_password=hash_password("secret"),
        full_name="Tabulação Test Owner",
    )
    db_session.add(user)
    await db_session.flush()

    agent = Agent(
        user_id=user.id,
        name=f"Agent_{suffix}",
        mode=AgentMode.ACTIVE,
        status="active",
    )
    db_session.add(agent)
    await db_session.flush()

    campaign = Campaign(
        user_id=user.id,
        agent_id=agent.id,
        name=f"Campaign_{suffix}",
        status="active",
    )
    db_session.add(campaign)
    await db_session.flush()

    lead_base = LeadBase(
        campaign_id=campaign.id,
        data_recebimento=date.today(),
        source=LeadBaseSource.MANUAL,
    )
    db_session.add(lead_base)
    await db_session.flush()

    lead = Lead(
        user_id=user.id,
        lead_base_id=lead_base.id,
        id_cliente=f"CLI-{suffix}",
        nome_cliente="Lead Tabulação",
        telefone_1="5511999887766",
    )
    db_session.add(lead)
    await db_session.flush()

    return OwnerContext(
        user=user,
        agent=agent,
        campaign=campaign,
        lead_base=lead_base,
        lead=lead,
    )


@pytest_asyncio.fixture
async def lead_interaction(owner_ctx: OwnerContext, db_session) -> LeadInteraction:
    li = LeadInteraction(
        lead_id=owner_ctx.lead.id,
        campaign_id=owner_ctx.campaign.id,
        channel_type="whatsapp",
        status="em_andamento",
        tentativas=1,
        data_acionamento=datetime.now(timezone.utc),
    )
    db_session.add(li)
    await db_session.flush()
    await db_session.refresh(li, attribute_names=["campaign_id"])
    li.campaign = owner_ctx.campaign
    return li


@pytest.fixture
def mock_classify(monkeypatch):
    """Mock de classify_tabulacao (LLM) — state['return_value'] controla o código."""
    state: dict = {"return_value": "NEG:NUM_ERRADO", "calls": []}

    async def fake_classify(text: str, catalog: list[dict[str, str]]) -> str | None:
        state["calls"].append(
            {
                "text": text,
                "catalog_codigos": [row["codigo"] for row in catalog],
            }
        )
        return state["return_value"]

    monkeypatch.setattr(
        "app.services.tabulacao_assignment.classify_tabulacao",
        fake_classify,
    )
    return state


# --- 1. Regras intent/status ---


async def test_rule_purchase_maps_to_neg_venda(lead_interaction, db_session) -> None:
    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        intent="purchase",
        status_interno="convertido",
        channel="whatsapp",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:VENDA"
    assert lead_interaction.tabulacao_origem == "INTENT"
    assert lead_interaction.tabulacao_aplicada_em is not None


async def test_rule_cancel_maps_to_neg_recusado(lead_interaction, db_session) -> None:
    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        intent="cancel",
        status_interno="recusou",
        channel="whatsapp",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:RECUSADO"
    assert lead_interaction.tabulacao_origem == "INTENT"
    assert lead_interaction.tabulacao_aplicada_em is not None


async def test_rule_nao_atendido_maps_to_neg_ausente(lead_interaction, db_session) -> None:
    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        status_interno="nao_atendido",
        channel="whatsapp",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:AUSENTE"
    assert lead_interaction.tabulacao_origem == "INTENT"


# --- 2. SIP ---


async def test_sip_busy_maps_to_sip_486(lead_interaction, db_session) -> None:
    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        sip_code="486",
        status_interno="em_andamento",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "SIP:486"
    assert lead_interaction.tabulacao_origem == "SIP"
    assert lead_interaction.tabulacao_aplicada_em is not None


# --- 3. Escalation ---


async def test_escalation_maps_to_neg_escalado(lead_interaction, db_session) -> None:
    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        escalated=True,
        status_interno="em_andamento",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:ESCALADO"
    assert lead_interaction.tabulacao_origem == "ESCALATION"


async def test_escalation_precedes_sip(lead_interaction, db_session) -> None:
    """Ordem real: escalation > SIP > regras > IA."""
    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        escalated=True,
        sip_code="486",
        status_interno="em_andamento",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:ESCALADO"
    assert lead_interaction.tabulacao_origem == "ESCALATION"


# --- 4. IA (mock) ---


async def test_ia_classifies_when_rules_do_not_resolve(
    lead_interaction, db_session, mock_classify
) -> None:
    mock_classify["return_value"] = "NEG:NUM_ERRADO"
    lead_interaction.devolutiva = "Cliente disse que o número está errado."

    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        status_interno="erro",
        channel="whatsapp",
        conversation_text=lead_interaction.devolutiva,
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:NUM_ERRADO"
    assert lead_interaction.tabulacao_origem == "IA"
    assert len(mock_classify["calls"]) == 1


async def test_ia_not_called_when_rule_resolves(
    lead_interaction, db_session, mock_classify
) -> None:
    mock_classify["return_value"] = "NEG:ABANDONO"
    lead_interaction.devolutiva = "Quero comprar agora."

    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        intent="purchase",
        status_interno="convertido",
        channel="whatsapp",
        conversation_text=lead_interaction.devolutiva,
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:VENDA"
    assert lead_interaction.tabulacao_origem == "INTENT"
    assert mock_classify["calls"] == []


# --- 5. maybe_apply_tabulacao_on_transition ---


async def test_maybe_apply_on_terminal_transition(lead_interaction, db_session) -> None:
    applied = await maybe_apply_tabulacao_on_transition(
        db_session,
        lead_interaction,
        status_interno="nao_atendido",
        channel="whatsapp",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:AUSENTE"


async def test_maybe_apply_skips_non_classification_transition(
    lead_interaction, db_session
) -> None:
    applied = await maybe_apply_tabulacao_on_transition(
        db_session,
        lead_interaction,
        intent="question",
        status_interno="em_andamento",
        channel="whatsapp",
    )

    assert applied is False
    assert lead_interaction.tabulacao_id is None


async def test_maybe_apply_on_escalation(lead_interaction, db_session) -> None:
    applied = await maybe_apply_tabulacao_on_transition(
        db_session,
        lead_interaction,
        escalated=True,
        status_interno="em_andamento",
    )

    assert applied is True
    assert await _codigo_for(db_session, lead_interaction) == "NEG:ESCALADO"


# --- 6. Lookup system vs owner ---


async def test_owner_custom_tabulacao_resolved_by_user_id(
    owner_ctx: OwnerContext, lead_interaction, db_session
) -> None:
    custom_codigo = f"CUSTOM:{uuid.uuid4().hex[:6].upper()}"
    custom = Tabulacao(
        user_id=owner_ctx.user.id,
        nome="Resultado Custom",
        codigo=custom_codigo,
        categoria=TabulacaoCategoria.CUSTOMIZADO.value,
        is_terminal=True,
        is_system=False,
    )
    db_session.add(custom)
    await db_session.flush()

    applied = await apply_tabulacao(
        db_session,
        lead_interaction,
        tabulacao_codigo=custom_codigo,
        status_interno="em_andamento",
    )

    assert applied is True
    assert lead_interaction.tabulacao_id == custom.id
    assert lead_interaction.tabulacao_origem == "HANDOFF_FINALIZE"


async def test_ia_catalog_includes_system_and_owner_custom(
    owner_ctx: OwnerContext, lead_interaction, db_session, mock_classify
) -> None:
    custom_codigo = f"CUSTOM:{uuid.uuid4().hex[:6].upper()}"
    db_session.add(
        Tabulacao(
            user_id=owner_ctx.user.id,
            nome="Custom IA",
            codigo=custom_codigo,
            categoria=TabulacaoCategoria.CUSTOMIZADO.value,
            is_terminal=True,
            is_system=False,
        )
    )
    await db_session.flush()

    mock_classify["return_value"] = custom_codigo
    lead_interaction.devolutiva = "Situação atípica sem regra."

    await apply_tabulacao(
        db_session,
        lead_interaction,
        status_interno="erro",
        conversation_text=lead_interaction.devolutiva,
    )

    assert len(mock_classify["calls"]) == 1
    catalog = mock_classify["calls"][0]["catalog_codigos"]
    assert "NEG:VENDA" in catalog
    assert "SIP:486" in catalog
    assert custom_codigo in catalog


# --- 7. Sobrescrita ---


async def test_apply_overwrites_existing_tabulacao(lead_interaction, db_session) -> None:
    first = await apply_tabulacao(
        db_session,
        lead_interaction,
        intent="purchase",
        status_interno="convertido",
    )
    assert first is True
    first_id = lead_interaction.tabulacao_id
    first_origem = lead_interaction.tabulacao_origem

    second = await apply_tabulacao(
        db_session,
        lead_interaction,
        sip_code="486",
        status_interno="em_andamento",
    )
    assert second is True
    assert lead_interaction.tabulacao_id != first_id
    assert await _codigo_for(db_session, lead_interaction) == "SIP:486"
    assert lead_interaction.tabulacao_origem == "SIP"
    assert lead_interaction.tabulacao_origem != first_origem
