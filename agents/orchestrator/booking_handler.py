"""Orquestração do fluxo conversacional de agendamento (texto — WhatsApp/Telegram)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from agents.memory.booking_state import (
    clear_booking_state,
    get_booking_state,
    is_active_booking_phase,
    parse_slot,
    serialize_slot,
    set_booking_state,
)
from agents.orchestrator.state import AgentState
from agents.tools.calendar_tool import create_appointment, list_available_slots
from agents.workers.booking_agent import (
    extract_booking_confirmation,
    extract_slot_choice,
)
from app.core.config import (
    APPOINTMENT_DEFAULT_WEEKDAYS,
    APPOINTMENT_TIMEZONE,
    settings,
)
from app.models.appointment import AppointmentSource

logger = logging.getLogger(__name__)

TEXT_CHANNELS = frozenset({"whatsapp", "telegram"})

CHOICE_CONFIDENCE_THRESHOLD = 0.55
CONFIRMATION_CONFIDENCE_THRESHOLD = 0.55


def _booking_applicable(state: AgentState) -> bool:
    channel = (state.get("channel") or "").lower()
    if channel not in TEXT_CHANNELS:
        return False
    intent = (state.get("intent") or "").lower()
    if intent == "schedule":
        return True
    existing = get_booking_state(channel, state["user_id"])
    if not existing:
        return False
    return is_active_booking_phase(existing.get("phase"))


def booking_search_range(num_business_days: int | None = None) -> tuple[datetime, datetime]:
    """Intervalo UTC cobrindo os próximos N dias úteis (inclusive hoje se útil)."""
    days = num_business_days or settings.booking_offer_business_days
    tz = ZoneInfo(APPOINTMENT_TIMEZONE)
    now = datetime.now(tz)
    start_utc = now.astimezone(timezone.utc)

    counted = 0
    cursor = now.date()
    if cursor.weekday() in APPOINTMENT_DEFAULT_WEEKDAYS:
        counted = 1

    while counted < days:
        cursor += timedelta(days=1)
        if cursor.weekday() in APPOINTMENT_DEFAULT_WEEKDAYS:
            counted += 1

    end_local = datetime.combine(cursor, time(23, 59, 59), tzinfo=tz)
    return start_utc, end_local.astimezone(timezone.utc)


def _index_offered_slots(raw_slots: list[dict], max_slots: int) -> list[dict]:
    indexed: list[dict] = []
    for idx, slot in enumerate(raw_slots[:max_slots], start=1):
        starts = slot["starts_at"]
        ends = slot["ends_at"]
        if isinstance(starts, str):
            starts = datetime.fromisoformat(starts)
        if isinstance(ends, str):
            ends = datetime.fromisoformat(ends)
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        indexed.append(
            serialize_slot(starts, ends, str(slot.get("label", "")), idx)
        )
    return indexed


async def _fetch_offered_slots(owner_user_id: str) -> list[dict]:
    from_dt, to_dt = booking_search_range()
    slots = await list_available_slots(owner_user_id, from_dt, to_dt)
    return _index_offered_slots(slots, settings.booking_max_offered_slots)


def _slot_still_in_list(selected: dict, offered: list[dict]) -> bool:
    sel_start = selected["starts_at"]
    sel_end = selected["ends_at"]
    for item in offered:
        parsed = parse_slot(item)
        if parsed["starts_at"] == sel_start and parsed["ends_at"] == sel_end:
            return True
    return False


def format_booking_context_block(instructions: str) -> str:
    return (
        "Contexto de AGENDAMENTO (instruções operacionais — o sistema já executou a lógica; "
        "sua tarefa é redigir a resposta ao cliente de forma natural e cordial):\n"
        f"{instructions.strip()}"
    )


def _degraded_context(reason: str) -> str:
    return format_booking_context_block(
        f"Não foi possível concluir o agendamento automaticamente ({reason}). "
        "Peça desculpas, explique que não conseguiu agendar agora e convide o cliente a "
        "tentar novamente em instantes ou informar outro período de preferência. "
        "Não invente horários."
    )


def _offering_context(slots: list[dict], lead_name: str | None) -> str:
    name = lead_name or "cliente"
    lines = [
        f"Fase: apresentar horários disponíveis para {name}.",
        "Apresente as opções abaixo de forma natural (pode numerar). "
        "Peça que o cliente escolha UMA opção.",
        "Horários disponíveis:",
    ]
    for slot in slots:
        lines.append(f"  {slot['index']}. {slot['label']}")
    return format_booking_context_block("\n".join(lines))


def _no_slots_context() -> str:
    return format_booking_context_block(
        "Não há horários livres nos próximos dias úteis no horário comercial. "
        "Informe isso com empatia e pergunte se o cliente prefere outro período "
        "(ex.: semana seguinte ou horário específico) — NÃO invente horários."
    )


def _clarify_context(slots: list[dict]) -> str:
    lines = [
        "Fase: esclarecimento — a escolha do cliente NÃO ficou clara.",
        "NÃO confirme nenhum agendamento. Repita as opções e peça que escolha "
        "uma delas (número ou horário).",
        "Opções:",
    ]
    for slot in slots:
        lines.append(f"  {slot['index']}. {slot['label']}")
    return format_booking_context_block("\n".join(lines))


def _confirm_context(selected: dict) -> str:
    return format_booking_context_block(
        f"Fase: confirmação final. O cliente escolheu: {selected['label']}.\n"
        "Peça confirmação explícita (sim/não) antes de concluir. "
        "NÃO diga que já está agendado — aguardamos a confirmação."
    )


def _success_context(selected: dict) -> str:
    return format_booking_context_block(
        f"Fase: concluído. O agendamento para {selected['label']} foi registrado com sucesso. "
        "Confirme ao cliente de forma clara e cordial, repetindo data e horário."
    )


def _conflict_context(slots: list[dict]) -> str:
    lines = [
        "O horário escolhido acabou de ser ocupado por outro cliente.",
        "Peça desculpas e ofereça novamente as opções ainda disponíveis:",
    ]
    for slot in slots:
        lines.append(f"  {slot['index']}. {slot['label']}")
    return format_booking_context_block("\n".join(lines))


async def _start_booking(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
) -> dict:
    slots = await _fetch_offered_slots(owner_user_id)
    if not slots:
        clear_booking_state(channel, user_id)
        return {"booking_context": _no_slots_context(), "booking_phase": "done"}

    payload = {
        "phase": "awaiting_choice",
        "offered_slots": slots,
        "selected_slot": None,
    }
    set_booking_state(channel, user_id, payload)
    return {
        "booking_context": _offering_context(slots, state.get("lead_name")),
        "booking_phase": "awaiting_choice",
    }


async def _handle_awaiting_choice(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    booking: dict,
) -> dict:
    offered = booking.get("offered_slots") or []
    if not offered:
        return await _start_booking(state, channel, user_id, owner_user_id)

    choice = await extract_slot_choice(
        state["message"],
        state.get("conversation_history", []),
        offered,
    )

    is_clear = (
        choice.choice == "clear"
        and choice.selected_index is not None
        and choice.confidence >= CHOICE_CONFIDENCE_THRESHOLD
    )

    if not is_clear or choice.choice in ("none", "unclear"):
        return {
            "booking_context": _clarify_context(offered),
            "booking_phase": "awaiting_choice",
        }

    selected_raw = next(
        (s for s in offered if int(s.get("index", -1)) == choice.selected_index),
        None,
    )
    if selected_raw is None:
        return {
            "booking_context": _clarify_context(offered),
            "booking_phase": "awaiting_choice",
        }

    selected = parse_slot(selected_raw)
    fresh_slots = await _fetch_offered_slots(owner_user_id)
    if not _slot_still_in_list(selected, fresh_slots):
        if fresh_slots:
            set_booking_state(
                channel,
                user_id,
                {
                    "phase": "awaiting_choice",
                    "offered_slots": fresh_slots,
                    "selected_slot": None,
                },
            )
            return {
                "booking_context": _conflict_context(fresh_slots),
                "booking_phase": "awaiting_choice",
            }
        clear_booking_state(channel, user_id)
        return {"booking_context": _no_slots_context(), "booking_phase": "done"}

    serializable_selected = serialize_slot(
        selected["starts_at"],
        selected["ends_at"],
        selected["label"],
        selected["index"],
    )
    set_booking_state(
        channel,
        user_id,
        {
            "phase": "confirming",
            "offered_slots": offered,
            "selected_slot": serializable_selected,
        },
    )
    return {
        "booking_context": _confirm_context(selected),
        "booking_phase": "confirming",
    }


async def _handle_confirming(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    booking: dict,
) -> dict:
    selected_raw = booking.get("selected_slot")
    if not selected_raw:
        return await _start_booking(state, channel, user_id, owner_user_id)

    selected = parse_slot(selected_raw)
    confirmation = await extract_booking_confirmation(
        state["message"],
        state.get("conversation_history", []),
        selected,
    )

    is_yes = (
        confirmation.decision == "yes"
        and confirmation.confidence >= CONFIRMATION_CONFIDENCE_THRESHOLD
    )
    is_no = (
        confirmation.decision == "no"
        and confirmation.confidence >= CONFIRMATION_CONFIDENCE_THRESHOLD
    )

    if not is_yes and not is_no:
        return {
            "booking_context": _confirm_context(selected),
            "booking_phase": "confirming",
        }

    if is_no:
        return await _start_booking(state, channel, user_id, owner_user_id)

    lead_id = state.get("lead_id")
    if not lead_id:
        clear_booking_state(channel, user_id)
        return {
            "booking_context": _degraded_context("lead não identificado"),
            "booking_phase": "done",
        }

    title = f"Agendamento via {channel}"
    result = await create_appointment(
        owner_user_id,
        lead_id,
        selected["starts_at"],
        selected["ends_at"],
        title=title,
        agent_id=state.get("agent_id"),
        channel=channel,
        created_by=AppointmentSource.AGENT.value,
    )

    if not result.get("ok"):
        error = result.get("error")
        if error == "slot_conflict":
            fresh = await _fetch_offered_slots(owner_user_id)
            if fresh:
                set_booking_state(
                    channel,
                    user_id,
                    {
                        "phase": "awaiting_choice",
                        "offered_slots": fresh,
                        "selected_slot": None,
                    },
                )
                return {
                    "booking_context": _conflict_context(fresh),
                    "booking_phase": "awaiting_choice",
                }
            clear_booking_state(channel, user_id)
            return {"booking_context": _no_slots_context(), "booking_phase": "done"}
        clear_booking_state(channel, user_id)
        return {
            "booking_context": _degraded_context(result.get("message", "erro interno")),
            "booking_phase": "done",
        }

    clear_booking_state(channel, user_id)
    return {
        "booking_context": _success_context(selected),
        "booking_phase": "done",
    }


async def process_booking_turn(state: AgentState) -> dict:
    """
    Avança o fluxo de agendamento e retorna booking_context para o response_agent.

    No-op rápido fora de canais de texto ou quando o fluxo não se aplica.
    """
    if not _booking_applicable(state):
        return {}

    channel = (state.get("channel") or "").lower()
    user_id = state["user_id"]
    owner_user_id = state.get("owner_user_id")
    lead_id = state.get("lead_id")

    if not owner_user_id:
        if (state.get("intent") or "").lower() == "schedule":
            return {"booking_context": _degraded_context("tenant não identificado")}
        return {}

    if not lead_id and (state.get("intent") or "").lower() == "schedule":
        return {"booking_context": _degraded_context("lead não identificado")}

    try:
        uuid.UUID(str(owner_user_id))
    except (ValueError, TypeError):
        return {"booking_context": _degraded_context("tenant inválido")}

    booking = get_booking_state(channel, user_id)
    phase = (booking or {}).get("phase")
    intent = (state.get("intent") or "").lower()

    if booking is None and intent == "schedule":
        return await _start_booking(state, channel, user_id, str(owner_user_id))

    if booking is None:
        return {}

    if phase == "awaiting_choice":
        return await _handle_awaiting_choice(
            state, channel, user_id, str(owner_user_id), booking
        )

    if phase == "confirming":
        return await _handle_confirming(
            state, channel, user_id, str(owner_user_id), booking
        )

    if phase == "offering":
        return await _start_booking(state, channel, user_id, str(owner_user_id))

    return {}
