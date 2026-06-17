"""Orquestração do fluxo conversacional de agendamento (texto e voz)."""

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

BOOKING_CHANNELS = frozenset({"whatsapp", "telegram", "voice"})
TEXT_LIST_CHANNELS = frozenset({"whatsapp", "telegram"})

CHOICE_CONFIDENCE_THRESHOLD = 0.55
CONFIRMATION_CONFIDENCE_THRESHOLD = 0.55


def _is_voice_channel(channel: str) -> bool:
    return (channel or "").lower() == "voice"


def _booking_applicable(state: AgentState) -> bool:
    channel = (state.get("channel") or "").lower()
    if channel not in BOOKING_CHANNELS:
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


async def _fetch_voice_slot_pool(owner_user_id: str) -> list[dict]:
    """Pool completo de slots para iteração 1-por-vez na voz."""
    from_dt, to_dt = booking_search_range()
    slots = await list_available_slots(owner_user_id, from_dt, to_dt)
    if not slots:
        return []
    return _index_offered_slots(slots, len(slots))


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


def _degraded_context(reason: str, *, voice: bool = False) -> str:
    body = (
        f"Não foi possível concluir o agendamento automaticamente ({reason}). "
        "Peça desculpas, explique que não conseguiu agendar agora e convide o cliente a "
        "tentar novamente em instantes ou informar outro período de preferência. "
        "Não invente horários."
    )
    if voice:
        body = (
            "Modo VOZ — UMA frase curta (máx. ~80 caracteres). "
            + body
        )
    return format_booking_context_block(body)


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


def _no_slots_context(*, voice: bool = False) -> str:
    if voice:
        return format_booking_context_block(
            "Modo VOZ — UMA frase curta (máx. ~80 caracteres). "
            "Não há horários livres nos próximos dias úteis. "
            "Informe com empatia e convide a tentar outro período. NÃO invente horários."
        )
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


def _success_context(selected: dict, *, voice: bool = False) -> str:
    if voice:
        return format_booking_context_block(
            f"Modo VOZ — UMA frase curta (máx. ~80 caracteres). "
            f"Agendamento confirmado: {selected['label']}. "
            "Agradeça e repita data/hora brevemente."
        )
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


def _voice_offer_context(slot: dict, lead_name: str | None) -> str:
    label = slot.get("label", "")
    name = lead_name or "você"
    return format_booking_context_block(
        "Modo VOZ — responda em UMA frase curta (máx. ~80 caracteres). "
        f"Ofereça o horário {label} para {name} e pergunte se serve "
        f'(ex.: "Tenho {label}, serve?"). '
        "NÃO liste outros horários. NÃO use numeração."
    )


def _voice_repeat_context(slot: dict) -> str:
    label = slot.get("label", "")
    return format_booking_context_block(
        "Modo VOZ — UMA frase curta (máx. ~80 caracteres). "
        "A resposta do cliente não ficou clara. "
        f'Repita: "{label}, serve para você?"'
    )


def _voice_next_offer_context(slot: dict) -> str:
    label = slot.get("label", "")
    return format_booking_context_block(
        "Modo VOZ — UMA frase curta (máx. ~80 caracteres). "
        "O horário anterior não serviu. "
        f'Ofereça: "{label}, serve?"'
    )


def _voice_no_more_slots_context() -> str:
    return format_booking_context_block(
        "Modo VOZ — UMA frase curta (máx. ~80 caracteres). "
        "Não há mais horários livres no período. "
        "Informe com empatia e convide a tentar outro dia."
    )


def _voice_state_payload(all_slots: list[dict], cursor: int = 0) -> dict:
    current = all_slots[cursor]
    return {
        "phase": "awaiting_choice",
        "voice_mode": True,
        "all_slots": all_slots,
        "slot_cursor": cursor,
        "offered_slots": [current],
        "selected_slot": None,
    }


def _current_voice_slot(booking: dict) -> dict:
    all_slots = booking.get("all_slots") or []
    cursor = int(booking.get("slot_cursor", 0))
    if not all_slots or cursor >= len(all_slots):
        offered = booking.get("offered_slots") or []
        if offered:
            return parse_slot(offered[0])
        raise ValueError("voice booking without current slot")
    return parse_slot(all_slots[cursor])


async def _commit_booking(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    selected: dict,
    *,
    voice_mode: bool = False,
    booking: dict | None = None,
) -> dict:
    lead_id = state.get("lead_id")
    if not lead_id:
        clear_booking_state(channel, user_id)
        return {
            "booking_context": _degraded_context("lead não identificado", voice=voice_mode),
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
            if voice_mode and booking is not None:
                return await _voice_advance_after_conflict(
                    state, channel, user_id, owner_user_id, booking
                )
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
            "booking_context": _degraded_context(
                result.get("message", "erro interno"),
                voice=voice_mode,
            ),
            "booking_phase": "done",
        }

    clear_booking_state(channel, user_id)
    return {
        "booking_context": _success_context(selected, voice=voice_mode),
        "booking_phase": "done",
    }


async def _start_booking_text(
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


async def _start_booking_voice(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
) -> dict:
    all_slots = await _fetch_voice_slot_pool(owner_user_id)
    if not all_slots:
        clear_booking_state(channel, user_id)
        return {"booking_context": _no_slots_context(voice=True), "booking_phase": "done"}

    payload = _voice_state_payload(all_slots, cursor=0)
    set_booking_state(channel, user_id, payload)
    current = parse_slot(all_slots[0])
    return {
        "booking_context": _voice_offer_context(current, state.get("lead_name")),
        "booking_phase": "awaiting_choice",
    }


async def _start_booking(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
) -> dict:
    if _is_voice_channel(channel):
        return await _start_booking_voice(state, channel, user_id, owner_user_id)
    return await _start_booking_text(state, channel, user_id, owner_user_id)


async def _voice_offer_at_cursor(
    state: AgentState,
    channel: str,
    user_id: str,
    all_slots: list[dict],
    cursor: int,
    *,
    repeat: bool = False,
    after_reject: bool = False,
) -> dict:
    current = parse_slot(all_slots[cursor])
    set_booking_state(
        channel,
        user_id,
        _voice_state_payload(all_slots, cursor=cursor),
    )
    if repeat:
        ctx = _voice_repeat_context(current)
    elif after_reject:
        ctx = _voice_next_offer_context(current)
    else:
        ctx = _voice_offer_context(current, state.get("lead_name"))
    return {"booking_context": ctx, "booking_phase": "awaiting_choice"}


async def _voice_advance_slot(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    booking: dict,
) -> dict:
    all_slots = booking.get("all_slots") or []
    next_cursor = int(booking.get("slot_cursor", 0)) + 1
    if next_cursor >= len(all_slots):
        clear_booking_state(channel, user_id)
        return {
            "booking_context": _voice_no_more_slots_context(),
            "booking_phase": "done",
        }
    return await _voice_offer_at_cursor(
        state, channel, user_id, all_slots, next_cursor, after_reject=True
    )


async def _voice_advance_after_conflict(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    booking: dict,
) -> dict:
    fresh = await _fetch_voice_slot_pool(owner_user_id)
    if not fresh:
        clear_booking_state(channel, user_id)
        return {
            "booking_context": _no_slots_context(voice=True),
            "booking_phase": "done",
        }
    cursor = int(booking.get("slot_cursor", 0)) + 1
    if cursor >= len(fresh):
        clear_booking_state(channel, user_id)
        return {
            "booking_context": _voice_no_more_slots_context(),
            "booking_phase": "done",
        }
    return await _voice_offer_at_cursor(
        state, channel, user_id, fresh, cursor, after_reject=True
    )


async def _handle_voice_awaiting_choice(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    booking: dict,
) -> dict:
    try:
        selected = _current_voice_slot(booking)
    except ValueError:
        return await _start_booking_voice(state, channel, user_id, owner_user_id)

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

    if is_yes:
        fresh = await _fetch_voice_slot_pool(owner_user_id)
        if not _slot_still_in_list(selected, fresh):
            return await _voice_advance_after_conflict(
                state, channel, user_id, owner_user_id, booking
            )
        return await _commit_booking(
            state,
            channel,
            user_id,
            owner_user_id,
            selected,
            voice_mode=True,
            booking=booking,
        )

    if is_no:
        return await _voice_advance_slot(
            state, channel, user_id, owner_user_id, booking
        )

    return {
        "booking_context": _voice_repeat_context(selected),
        "booking_phase": "awaiting_choice",
    }


async def _handle_awaiting_choice(
    state: AgentState,
    channel: str,
    user_id: str,
    owner_user_id: str,
    booking: dict,
) -> dict:
    if booking.get("voice_mode"):
        return await _handle_voice_awaiting_choice(
            state, channel, user_id, owner_user_id, booking
        )

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
    if booking.get("voice_mode"):
        return await _handle_voice_awaiting_choice(
            state, channel, user_id, owner_user_id, booking
        )

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

    return await _commit_booking(
        state, channel, user_id, owner_user_id, selected, voice_mode=False
    )


async def process_booking_turn(state: AgentState) -> dict:
    """
    Avança o fluxo de agendamento e retorna booking_context para o response_agent.

    No-op rápido quando o fluxo não se aplica ao canal/intent.
    """
    if not _booking_applicable(state):
        return {}

    channel = (state.get("channel") or "").lower()
    user_id = state["user_id"]
    owner_user_id = state.get("owner_user_id")
    lead_id = state.get("lead_id")
    voice = _is_voice_channel(channel)

    if not owner_user_id:
        if (state.get("intent") or "").lower() == "schedule":
            return {"booking_context": _degraded_context("tenant não identificado", voice=voice)}
        return {}

    if not lead_id and (state.get("intent") or "").lower() == "schedule":
        return {"booking_context": _degraded_context("lead não identificado", voice=voice)}

    try:
        uuid.UUID(str(owner_user_id))
    except (ValueError, TypeError):
        return {"booking_context": _degraded_context("tenant inválido", voice=voice)}

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
