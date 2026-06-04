"""Normalização de telefone compartilhada entre canais (WhatsApp, voz PSTN, tracking)."""

from __future__ import annotations

import re


def normalize_phone_digits(phone: str) -> str:
    """Remove +, espaços, traços, parênteses; retorna só dígitos."""
    return re.sub(r"\D", "", phone)


def to_e164(phone: str, default_country: str = "55") -> str:
    """Converte telefone brasileiro (ou já internacional) para E.164 (+55...)."""
    digits = normalize_phone_digits(phone)
    if not digits:
        raise ValueError("Telefone vazio ou inválido")

    country = normalize_phone_digits(default_country) or "55"

    if digits.startswith(country) and len(digits) >= len(country) + 8:
        return f"+{digits}"

    if digits.startswith("00"):
        return f"+{digits[2:]}"

    return f"+{country}{digits}"
