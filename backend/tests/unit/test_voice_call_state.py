"""Unit tests — estado Redis de silêncio na voz."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.voice_call_state import (
    add_accumulated_silence,
    clear_voice_call_state,
    get_accumulated_silence_sec,
    get_silence_stage,
    get_voice_call_state,
    reset_silence_stage,
    set_voice_call_state,
)


def test_silence_stage_defaults_to_zero() -> None:
    with patch("app.services.voice_call_state._get_redis") as mock_redis:
        mock_redis.return_value.get.return_value = None
        assert get_silence_stage("CA-test") == 0


def test_set_and_read_silence_stage() -> None:
    client = MagicMock()
    payload = {}

    def setex(key, ttl, value):
        payload["key"] = key
        payload["value"] = value

    def get(key):
        return payload.get("value")

    client.setex.side_effect = setex
    client.get.side_effect = get

    with patch("app.services.voice_call_state._get_redis", return_value=client):
        set_voice_call_state("CA-123", silence_stage=1, from_number="+5511999999999")
        assert get_silence_stage("CA-123") == 1
        state = get_voice_call_state("CA-123")
        assert state is not None
        assert state["from_number"] == "+5511999999999"
        reset_silence_stage("CA-123", from_number="+5511999999999")
        assert get_silence_stage("CA-123") == 0
        assert get_accumulated_silence_sec("CA-123") == 0.0
        clear_voice_call_state("CA-123")
        client.delete.assert_called_with("voice_call_state:CA-123")


def test_add_accumulated_silence_sums_intervals() -> None:
    client = MagicMock()
    payload = {}

    def setex(key, ttl, value):
        payload["value"] = value

    def get(key):
        return payload.get("value")

    client.setex.side_effect = setex
    client.get.side_effect = get

    with patch("app.services.voice_call_state._get_redis", return_value=client):
        total = add_accumulated_silence("CA-acc", 3.0, from_number="+5511888888888")
        assert total == 3.0
        total = add_accumulated_silence("CA-acc", 3.0)
        assert total == 6.0
