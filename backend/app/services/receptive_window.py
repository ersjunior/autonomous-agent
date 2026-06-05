"""Janela operacional do atendimento receptivo (R-A)."""

from __future__ import annotations

from typing import Any

from app.core.activation_window import is_within_window


def is_receptive_window_open(params: dict[str, Any]) -> bool:
    """
    Verifica janela do receptivo nos params do agente/canal.

    Default 00:00–23:59 é tratado como 24/7 (sempre aberto).
    """
    start = (params.get("receptivo_horario_inicio") or "00:00").strip()
    end = (params.get("receptivo_horario_fim") or "23:59").strip()
    if start == "00:00" and end == "23:59":
        return True
    return is_within_window(start, end)


def outside_receptive_window_message(params: dict[str, Any]) -> str:
    start = params.get("receptivo_horario_inicio", "09:00")
    end = params.get("receptivo_horario_fim", "18:00")
    return (
        f"Nosso atendimento funciona das {start} às {end}. "
        "Retornaremos na próxima janela de atendimento."
    )
