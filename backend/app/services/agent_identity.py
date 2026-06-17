"""Override de identidade institucional em agent.config.identity."""

from __future__ import annotations

from typing import Any

from agents.identity import IDENTITY_CONFIG_KEY, IDENTITY_FIELD_KEYS

from app.schemas.identity import InstitutionalIdentityUpdate, identity_dict_to_response


def extract_agent_identity_override(
    config: dict[str, Any] | None,
) -> dict[str, str]:
    """Campos de override gravados em agent.config.identity (sem merge com workspace)."""
    if not config or not isinstance(config, dict):
        return {}
    raw = config.get(IDENTITY_CONFIG_KEY)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key in IDENTITY_FIELD_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result[key] = text
    return result


def apply_agent_identity_patch(
    config: dict[str, Any] | None,
    payload: InstitutionalIdentityUpdate,
) -> dict[str, Any]:
    """
    Atualiza só agent.config.identity; preserva demais chaves do config.

    Campos None no payload removem o override (herda do workspace no merge da 2a).
    """
    base = dict(config or {})
    raw_identity = base.get(IDENTITY_CONFIG_KEY)
    identity: dict[str, str] = dict(raw_identity) if isinstance(raw_identity, dict) else {}

    patch = payload.model_dump()
    for key in IDENTITY_FIELD_KEYS:
        value = patch.get(key)
        if value is None:
            identity.pop(key, None)
        else:
            identity[key] = value

    if identity:
        base[IDENTITY_CONFIG_KEY] = identity
    else:
        base.pop(IDENTITY_CONFIG_KEY, None)
    return base


def agent_identity_response_from_config(config: dict[str, Any] | None):
    """Resposta API com overrides do agente (valores ausentes = herda workspace)."""
    return identity_dict_to_response(extract_agent_identity_override(config))
