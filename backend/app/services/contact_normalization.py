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
      - **whatsapp / voice / video (phone):** ``+5511...``, ``5511...``, ``whatsapp:+5511...``
      - **telegram:** exact chat id string (no prefix normalization)
    """
    ch = normalize_channel_type(channel)
    raw = (user_id or "").strip()
    if not raw:
        return []

    if ch == "telegram":
        return [raw]

    if ch in ("whatsapp", "voice", "video"):
        return _phone_variants(raw)

    return [raw]


def infer_channel_from_contact(user_id: str) -> str:
    """
    Infer messaging channel for orphan contacts (no LeadInteraction row).

    Used only when listing receptive contacts without a tracked lead interaction.
    """
    raw = (user_id or "").strip()
    if not raw:
        return "whatsapp"
    if _WHATSAPP_PREFIX_RE.match(raw):
        return "whatsapp"
    if raw.startswith("+") or raw.isdigit():
        return "whatsapp"
    return "telegram"
