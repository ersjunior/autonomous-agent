"""Institutional identity from agent.config.identity (admin-defined, prompt injection)."""

from __future__ import annotations

from typing import Any

IDENTITY_CONFIG_KEY = "identity"

IDENTITY_FIELD_KEYS: tuple[str, ...] = (
    "company_name",
    "display_name",
    "tone",
    "business_context",
    "greeting_hint",
)

_IDENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("company_name", "Empresa"),
    ("display_name", "Nome de exibição"),
    ("tone", "Tom"),
    ("business_context", "Contexto"),
    ("greeting_hint", "Saudação"),
)

_IDENTITY_RULES = (
    "Regras: esta identidade autoriza você a se apresentar com este nome e posicionamento. "
    "NÃO invente preços, prazos, políticas ou detalhes de produto que não estejam na base de "
    "conhecimento abaixo."
)


def _coerce_identity_dict(config: dict[str, Any] | None) -> dict[str, str]:
    if not config or not isinstance(config, dict):
        return {}
    raw = config.get(IDENTITY_CONFIG_KEY)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key, _label in _IDENTITY_FIELDS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result[key] = text
    return result


def merge_institutional_identity(
    workspace: dict[str, str] | None,
    agent: dict[str, str] | None,
) -> dict[str, str]:
    """
    Merge campo-a-campo: agente preenchido > workspace > omitido.
    """
    ws = workspace or {}
    ag = agent or {}
    merged: dict[str, str] = {}
    for key in IDENTITY_FIELD_KEYS:
        agent_val = str(ag.get(key) or "").strip()
        workspace_val = str(ws.get(key) or "").strip()
        if agent_val:
            merged[key] = agent_val
        elif workspace_val:
            merged[key] = workspace_val
    return merged


def resolve_identity_config(
    workspace_identity: dict[str, str] | None,
    agent_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Combina workspace + ``agent_config.identity`` e retorna config pronto para o prompt.

    Preserva chaves operacionais de ``agent_config`` (ex.: ``tipo``).
    """
    base = dict(agent_config or {})
    agent_identity: dict[str, Any] = {}
    raw_agent = base.get(IDENTITY_CONFIG_KEY)
    if isinstance(raw_agent, dict):
        agent_identity = raw_agent
    merged = merge_institutional_identity(workspace_identity, agent_identity)
    base[IDENTITY_CONFIG_KEY] = merged
    return base


def non_identity_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Config operacional sem a chave identity (para personality/debug)."""
    if not config or not isinstance(config, dict):
        return {}
    return {k: v for k, v in config.items() if k != IDENTITY_CONFIG_KEY}


def format_institutional_identity_block(config: dict[str, Any] | None) -> str | None:
    """
    Monta bloco de sistema a partir de ``config.identity``.

    Retorna None se identity ausente ou sem campos preenchidos.
    """
    identity = _coerce_identity_dict(config)
    if not identity:
        return None

    lines = [
        "Identidade institucional (definida pelo administrador — fonte autorizada para nome, "
        "marca, tom e contexto de negócio):",
    ]

    empresa = identity.get("display_name") or identity.get("company_name")
    if empresa:
        lines.append(f"- Empresa: {empresa}")

    for key, label in _IDENTITY_FIELDS:
        if key in ("company_name", "display_name"):
            continue
        if key in identity:
            lines.append(f"- {label}: {identity[key]}")

    lines.append(_IDENTITY_RULES)
    return "\n".join(lines)
