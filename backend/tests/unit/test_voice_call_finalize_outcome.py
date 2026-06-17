"""Unit tests — finalize_voice_call_terminal por origem."""

from __future__ import annotations

import pytest

from app.services.voice_call_finalize import (
    VOICE_FAREWELL_ORIGEM,
    VOICE_FAREWELL_TABULACAO,
    VOICE_TERMINAL_TABULACAO,
    _terminal_outcome_for_origem,
)

pytestmark = pytest.mark.unit


def test_farewell_origem_maps_to_success() -> None:
    status, tab = _terminal_outcome_for_origem(VOICE_FAREWELL_ORIGEM)
    assert status == "convertido"
    assert tab == VOICE_FAREWELL_TABULACAO


def test_silence_origem_maps_to_absent() -> None:
    status, tab = _terminal_outcome_for_origem("VOICE_SILENCE")
    assert status == "nao_atendido"
    assert tab == VOICE_TERMINAL_TABULACAO
