"""Structured extraction for conversational booking (slot choice and confirmation)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.provider_factory import ProviderFactory
from app.core.config import settings

SlotChoiceKind = Literal["clear", "none", "unclear"]
ConfirmationDecision = Literal["yes", "no", "unclear"]

SLOT_CHOICE_SYSTEM_PROMPT = """Você interpreta a resposta do cliente em um fluxo de AGENDAMENTO.
O cliente recebeu uma lista numerada de horários disponíveis e respondeu em texto livre.

Analise a mensagem atual e o histórico recente. Determine:
- choice=clear quando o cliente escolheu UM horário da lista (por número, data, dia ou hora).
- choice=unclear quando a resposta é ambígua, parcial ou não identifica um horário da lista.
- choice=none quando o cliente recusou todos, pediu outro período ou disse que nenhum serve.

Quando choice=clear, preencha selected_index com o número (1-based) do horário na lista oferecida.
Use confidence entre 0 e 1."""

CONFIRMATION_SYSTEM_PROMPT = """Você interpreta se o cliente CONFIRMA ou NÃO um agendamento proposto.
O atendente acabou de pedir confirmação de um horário específico.

Analise a mensagem atual e o histórico. Retorne:
- decision=yes quando o cliente confirma (sim, pode ser, confirmo, isso mesmo, fechado…).
- decision=no quando recusa, quer mudar ou cancelar o horário.
- decision=unclear quando não dá para saber se confirmou ou não.

Use confidence entre 0 e 1."""


class SlotChoiceResult(BaseModel):
    choice: SlotChoiceKind
    selected_index: int | None = Field(
        default=None,
        description="Índice 1-based na lista offered_slots quando choice=clear",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class BookingConfirmationResult(BaseModel):
    decision: ConfirmationDecision
    confidence: float = Field(ge=0.0, le=1.0)


def _history_to_text(history: list[dict]) -> str:
    return "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in history
    )


def _format_offered_slots_for_prompt(offered_slots: list[dict]) -> str:
    lines = ["Horários oferecidos ao cliente:"]
    for slot in offered_slots:
        idx = slot.get("index")
        label = slot.get("label", "")
        lines.append(f"  {idx}. {label}")
    return "\n".join(lines)


async def extract_slot_choice(
    message: str,
    history: list[dict],
    offered_slots: list[dict],
) -> SlotChoiceResult:
    llm = ProviderFactory.get_llm()
    history_text = _history_to_text(history)
    slots_text = _format_offered_slots_for_prompt(offered_slots)
    user_content = (
        f"{slots_text}\n\n"
        f"Histórico:\n{history_text}\n\n"
        f"Mensagem atual do cliente:\n{message}"
    )
    messages = [
        {"role": "system", "content": SLOT_CHOICE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    max_tokens = settings.intent_max_tokens
    result = await llm.complete(
        messages,
        temperature=settings.intent_temperature,
        structured_output_schema=SlotChoiceResult,
        max_tokens=max_tokens if max_tokens > 0 else None,
    )
    if not isinstance(result, SlotChoiceResult):
        raise TypeError(f"Expected SlotChoiceResult, got {type(result)}")
    return result


async def extract_booking_confirmation(
    message: str,
    history: list[dict],
    selected_slot: dict,
) -> BookingConfirmationResult:
    llm = ProviderFactory.get_llm()
    history_text = _history_to_text(history)
    label = selected_slot.get("label", "")
    user_content = (
        f"Horário proposto para confirmação: {label}\n\n"
        f"Histórico:\n{history_text}\n\n"
        f"Mensagem atual do cliente:\n{message}"
    )
    messages = [
        {"role": "system", "content": CONFIRMATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    max_tokens = settings.intent_max_tokens
    result = await llm.complete(
        messages,
        temperature=settings.intent_temperature,
        structured_output_schema=BookingConfirmationResult,
        max_tokens=max_tokens if max_tokens > 0 else None,
    )
    if not isinstance(result, BookingConfirmationResult):
        raise TypeError(f"Expected BookingConfirmationResult, got {type(result)}")
    return result
