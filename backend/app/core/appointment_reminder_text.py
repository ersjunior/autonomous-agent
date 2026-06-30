"""Textos fixos do lembrete proativo de agendamentos (voz/telegram/whatsapp)."""

from __future__ import annotations

from datetime import datetime

from app.services.appointment_service import format_slot_label


def build_reminder_message(starts_at: datetime) -> str:
    """Lembrete antecipado — horário por extenso via format_slot_label."""
    quando = format_slot_label(starts_at)
    return f"Ola! Passando para lembrar do seu agendamento {quando}."


def build_due_message(starts_at: datetime) -> str:
    """Acionamento na hora do compromisso."""
    quando = format_slot_label(starts_at)
    return f"Ola! Chegou o horario do seu agendamento ({quando}). Podemos comecar?"
