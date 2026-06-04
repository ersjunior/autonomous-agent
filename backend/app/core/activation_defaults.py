"""System defaults for agent channel activation parameters (Layer A)."""

from __future__ import annotations

from typing import Any

VOICE_VIDEO_CHANNELS = frozenset({"voice", "video"})
MESSAGING_CHANNELS = frozenset({"whatsapp", "telegram"})
SUPPORTED_CHANNEL_TYPES = VOICE_VIDEO_CHANNELS | MESSAGING_CHANNELS

_VOICE_VIDEO_DEFAULTS: dict[str, Any] = {
    "chamadas_simultaneas": 1,
    "campanhas_simultaneas": 1,
    "tentativas_por_hora": 6,
    "horario_inicio": "09:00",
    "horario_fim": "20:00",
}

_MESSAGING_DEFAULTS: dict[str, Any] = {
    "chats_simultaneos": 5,
    "campanhas_simultaneas": 1,
    "tentativas_sem_resposta": 2,
    "minutos_segunda_mensagem": 20,
    "horario_inicio": "09:00",
    "horario_fim": "20:00",
}

SYSTEM_CHANNEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "voice": dict(_VOICE_VIDEO_DEFAULTS),
    "video": dict(_VOICE_VIDEO_DEFAULTS),
    "whatsapp": dict(_MESSAGING_DEFAULTS),
    "telegram": dict(_MESSAGING_DEFAULTS),
}


def normalize_channel_type(channel_type: str) -> str:
    return channel_type.strip().lower()


def channel_family(channel_type: str) -> str:
    """Returns 'voice_video' or 'messaging'."""
    normalized = normalize_channel_type(channel_type)
    if normalized in VOICE_VIDEO_CHANNELS:
        return "voice_video"
    if normalized in MESSAGING_CHANNELS:
        return "messaging"
    raise ValueError(f"Unsupported channel type: {channel_type}")


def default_params_for_channel(channel_type: str) -> dict[str, Any]:
    normalized = normalize_channel_type(channel_type)
    if normalized not in SYSTEM_CHANNEL_DEFAULTS:
        raise ValueError(f"Unsupported channel type: {channel_type}")
    return dict(SYSTEM_CHANNEL_DEFAULTS[normalized])
