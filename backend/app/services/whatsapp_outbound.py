"""Decisão de envio WhatsApp — janela de 24h Meta e templates Content API (W3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from datetime import datetime

from app.core.config import WhatsAppTemplatePurpose, settings
from app.models.lead import Lead
from app.models.lead_interaction import LeadInteraction
from app.services.appointment_service import format_slot_label

WHATSAPP_SERVICE_WINDOW_HOURS = 24

WhatsAppSendKind = Literal["freeform", "template"]


@dataclass(frozen=True)
class WhatsAppSendMode:
    """Modo de envio resolvido para um outbound WhatsApp."""

    mode: WhatsAppSendKind
    content_sid: str | None = None
    content_variables: dict[str, str] | None = None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_within_whatsapp_service_window(record: LeadInteraction | None) -> bool:
    """
    True se o cliente respondeu nas últimas 24h (janela de atendimento Meta).

    False para lead frio (record None) ou sem inbound (data_ultimo_contato None).
    """
    if record is None:
        return False
    last_inbound = _aware(record.data_ultimo_contato)
    if last_inbound is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WHATSAPP_SERVICE_WINDOW_HOURS)
    return last_inbound >= cutoff


def build_content_variables(lead: Lead) -> dict[str, str]:
    """Variáveis do template Meta {{1}} = nome do lead."""
    name = (lead.nome_cliente or "Cliente").strip() or "Cliente"
    return {"1": name}


def build_appointment_content_variables(
    lead: Lead,
    starts_at: datetime,
) -> dict[str, str]:
    """Variáveis dos templates de agendamento: {{1}} = nome, {{2}} = data/hora."""
    name = (lead.nome_cliente or "Cliente").strip() or "Cliente"
    return {"1": name, "2": format_slot_label(starts_at)}


def resolve_whatsapp_send_mode(
    purpose: WhatsAppTemplatePurpose,
    record: LeadInteraction | None,
    *,
    lead: Lead | None = None,
    ignore_service_window: bool = False,
) -> WhatsAppSendMode:
    """
    Decide template vs texto livre.

    - Templates desligados → freeform (comportamento legado).
    - Dentro da janela de 24h → freeform (LLM / resposta conversacional).
    - Fora da janela → template do ``purpose`` (ContentSid + variáveis se ``lead``).
    - ``ignore_service_window=True`` ignora a janela de 24h (test-dispatch com templates).
    """
    if not settings.whatsapp_templates_enabled():
        return WhatsAppSendMode(mode="freeform")
    if not ignore_service_window and is_within_whatsapp_service_window(record):
        return WhatsAppSendMode(mode="freeform")

    content_sid = settings.resolved_whatsapp_template(purpose)
    if not content_sid:
        return WhatsAppSendMode(mode="freeform")

    variables = build_content_variables(lead) if lead is not None else None
    return WhatsAppSendMode(
        mode="template",
        content_sid=content_sid,
        content_variables=variables,
    )
