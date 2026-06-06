"""Testes unitários — normalização de telefone (agents/channels/phone)."""

from __future__ import annotations

import pytest

from agents.channels.phone import normalize_phone_digits, to_e164

pytestmark = pytest.mark.unit


class TestNormalizePhoneDigits:
    def test_strips_formatting(self) -> None:
        assert normalize_phone_digits("+55 11 99999-9999") == "5511999999999"
        assert normalize_phone_digits("(11) 99999-9999") == "11999999999"

    def test_already_digits_unchanged(self) -> None:
        assert normalize_phone_digits("5511999887766") == "5511999887766"

    def test_empty_returns_empty(self) -> None:
        assert normalize_phone_digits("") == ""


class TestToE164:
    def test_brazilian_local_number(self) -> None:
        assert to_e164("11 99999-9999") == "+5511999999999"

    def test_already_international(self) -> None:
        assert to_e164("+55 11 99999-9999") == "+5511999999999"
        assert to_e164("5511999999999") == "+5511999999999"

    def test_double_zero_international_prefix(self) -> None:
        assert to_e164("005511999999999") == "+5511999999999"

    def test_already_normalized_unchanged(self) -> None:
        e164 = "+5511999887766"
        assert to_e164(e164) == e164

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="vazio"):
            to_e164("")

    def test_custom_country_code(self) -> None:
        assert to_e164("2025551234", default_country="1") == "+12025551234"
