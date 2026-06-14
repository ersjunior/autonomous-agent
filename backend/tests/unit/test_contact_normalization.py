"""Testes unitários — normalização de identificadores de contato."""

from __future__ import annotations

import pytest

from app.services.contact_normalization import (
    canonical_contact_ids,
    infer_channel_from_contact,
)

pytestmark = pytest.mark.unit

PHONE = "+5511999887766"
PHONE_DIGITS = "5511999887766"


class TestCanonicalContactIds:
    def test_whatsapp_includes_e164_and_prefixed_variants(self) -> None:
        ids = canonical_contact_ids("whatsapp", PHONE)
        assert PHONE in ids
        assert f"whatsapp:{PHONE}" in ids

    def test_whatsapp_from_bare_digits_adds_plus_form(self) -> None:
        ids = canonical_contact_ids("whatsapp", PHONE_DIGITS)
        assert PHONE_DIGITS in ids
        assert PHONE in ids
        assert f"whatsapp:{PHONE}" in ids

    def test_whatsapp_prefix_input_normalized(self) -> None:
        ids = canonical_contact_ids("whatsapp", f"whatsapp:{PHONE}")
        assert PHONE in ids
        assert f"whatsapp:{PHONE}" in ids

    def test_voice_uses_phone_variants(self) -> None:
        voice_ids = canonical_contact_ids("voice", PHONE)
        whatsapp_ids = canonical_contact_ids("whatsapp", PHONE)
        assert voice_ids == whatsapp_ids
        assert PHONE in voice_ids

    def test_telegram_returns_exact_id(self) -> None:
        chat_id = "123456789"
        assert canonical_contact_ids("telegram", chat_id) == [chat_id]

    def test_empty_user_id_returns_empty_list(self) -> None:
        assert canonical_contact_ids("whatsapp", "") == []
        assert canonical_contact_ids("whatsapp", "   ") == []


class TestInferChannelFromContact:
    def test_whatsapp_prefix(self) -> None:
        assert infer_channel_from_contact(f"whatsapp:{PHONE}") == "whatsapp"

    def test_e164_phone(self) -> None:
        assert infer_channel_from_contact(PHONE) == "whatsapp"

    def test_bare_digits_treated_as_phone(self) -> None:
        # Lógica atual: isdigit() → whatsapp (limitação conhecida para chat ids numéricos)
        assert infer_channel_from_contact(PHONE_DIGITS) == "whatsapp"

    def test_alphanumeric_id_is_telegram(self) -> None:
        assert infer_channel_from_contact("user_abc_42") == "telegram"

    def test_empty_defaults_to_whatsapp(self) -> None:
        assert infer_channel_from_contact("") == "whatsapp"
