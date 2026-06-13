"""Integração — apply_tabulacao e atribuição híbrida (regras → SIP → IA / escalation)."""

from __future__ import annotations

import uuid

import pytest

from app.models.tabulacao import Tabulacao, TabulacaoCategoria
from app.services.tabulacao_assignment import (
    apply_tabulacao,
    maybe_apply_tabulacao_on_transition,
)
from tests.integration.helpers import OwnerContext, tabulacao_codigo_for

pytestmark = pytest.mark.integration


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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:VENDA"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:RECUSADO"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:AUSENTE"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "SIP:486"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:ESCALADO"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:ESCALADO"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:NUM_ERRADO"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:VENDA"
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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:AUSENTE"


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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "NEG:ESCALADO"


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
    assert await tabulacao_codigo_for(db_session, lead_interaction) == "SIP:486"
    assert lead_interaction.tabulacao_origem == "SIP"
    assert lead_interaction.tabulacao_origem != first_origem
