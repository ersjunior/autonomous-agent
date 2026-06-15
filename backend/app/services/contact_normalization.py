"""Normalize channel contact identifiers for cross-querying ``interactions.user_id``.

WhatsApp inbound (Twilio) stores ``whatsapp:+5511...`` while outbound uses ``+5511...``
from the lead record. Both must match when rebuilding conversation threads.
"""

from __future__ import annotations

import re

from agents.channels.phone import normalize_phone_digits
from app.core.activation_defaults import normalize_channel_type

_WHATSAPP_PREFIX_RE = re.compile(r"^whatsapp:\s*", re.IGNORECASE)


def _phone_variants(raw: str) -> list[str]:
    """E.164-ish and whatsapp:-prefixed forms for the same handset."""
    stripped = raw.strip()
    if not stripped:
        return []

    variants: list[str] = []
    if _WHATSAPP_PREFIX_RE.match(stripped):
        variants.append(stripped)
        bare = _WHATSAPP_PREFIX_RE.sub("", stripped).strip()
        if bare:
            variants.append(bare)
    else:
        variants.append(stripped)
        variants.append(f"whatsapp:{stripped}")

    digits = normalize_phone_digits(stripped)
    if digits:
        plus = f"+{digits}"
        variants.append(plus)
        variants.append(f"whatsapp:{plus}")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def canonical_contact_ids(channel: str, user_id: str) -> list[str]:
    """
    Return all ``interactions.user_id`` variants to search for a contact.

    Variations handled:
      - **whatsapp / voice (phone):** ``+5511...``, ``5511...``, ``whatsapp:+5511...``
      - **telegram:** exact chat id string (no prefix normalization)
    """
    ch = normalize_channel_type(channel)
    raw = (user_id or "").strip()
    if not raw:
        return []

    if ch == "telegram":
        return [raw]

    if ch in ("whatsapp", "voice"):
        return _phone_variants(raw)

    return [raw]


def _looks_like_brazil_phone_digits(digits: str) -> bool:
    """Bare digits matching Brazilian E.164 without ``+`` (``5511...``, 12–13 digits)."""
    return (
        digits.isdigit()
        and digits.startswith("55")
        and 12 <= len(digits) <= 13
    )


def infer_channel_from_contact(user_id: str) -> str:
    """
    Infer messaging channel for orphan contacts (no LeadInteraction row).

    Used only when listing receptive contacts without a tracked lead interaction.

    Heuristics:
      - ``whatsapp:+55...`` or ``+55...`` → whatsapp (voice shares phone format)
      - bare digits ``55`` + DDD + number (12–13 digits) → whatsapp
      - other numeric ids (e.g. ``5043259127`` telegram chat id) → telegram
      - non-numeric strings → telegram
    """
    raw = (user_id or "").strip()
    if not raw:
        return "whatsapp"
    if _WHATSAPP_PREFIX_RE.match(raw):
        return "whatsapp"
    if raw.startswith("+"):
        return "whatsapp"
    if raw.isdigit():
        if _looks_like_brazil_phone_digits(raw):
            return "whatsapp"
        return "telegram"
    return "telegram"
