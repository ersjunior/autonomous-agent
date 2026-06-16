"""Institutional identity from agent.config.identity (admin-defined, prompt injection)."""

from __future__ import annotations

from typing import Any

IDENTITY_CONFIG_KEY = "identity"

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
