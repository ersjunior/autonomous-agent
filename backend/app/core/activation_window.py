"""Time window helpers for activation motor Layer B."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.core.config import ACTIVATION_TIMEZONE


def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]))


def _local_now(now: datetime | None, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    return now.astimezone(zone)


def is_within_window(
    horario_inicio: str,
    horario_fim: str,
    now: datetime | None = None,
    tz: str = ACTIVATION_TIMEZONE,
) -> bool:
    """
    Verifica se o horário atual (no fuso ``tz``) está dentro da janela operacional.

    Janela no mesmo dia (inicio < fim): intervalo [inicio, fim) — início inclusivo,
    fim exclusivo. Ex.: 09:00–20:00 inclui 09:00 e exclui 20:00.

    Janela que cruza meia-noite (fim <= inicio): ex. 22:00–06:00 →
    dentro se hora >= inicio OU hora < fim.
    """
    start = _parse_hhmm(horario_inicio)
    end = _parse_hhmm(horario_fim)
    current = _local_now(now, tz).time()

    if start <= end:
        return start <= current < end
    return current >= start or current < end


def outside_window_reason(
    horario_inicio: str,
    horario_fim: str,
    now: datetime | None = None,
    tz: str = ACTIVATION_TIMEZONE,
) -> str:
    """Mensagem quando o motor está ligado mas fora da janela operacional."""
    del horario_fim, now, tz  # reservado para mensagens futuras mais precisas
    return f"fora da janela; retomará às {horario_inicio}"
