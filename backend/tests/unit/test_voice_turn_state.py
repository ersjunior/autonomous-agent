"""Unit tests — voice turn Redis state."""

from __future__ import annotations

import pytest

from app.services import voice_turn_state as vts

pytestmark = pytest.mark.unit


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(vts, "_redis_client", client)
    return client


def test_create_and_get_pending_turn(fake_redis) -> None:
    vts.create_pending_turn(
        call_sid="CA1",
        turn_id="t1",
        recording_url="https://rec",
        from_number="+5511",
    )
    data = vts.get_voice_turn("CA1", "t1")
    assert data is not None
    assert data["status"] == "pending"
    assert data["recording_url"] == "https://rec"
    assert data["from_number"] == "+5511"


def test_mark_ready_and_consumed(fake_redis) -> None:
    vts.create_pending_turn(
        call_sid="CA2",
        turn_id="t2",
        recording_url="https://rec",
        from_number="+5511",
    )
    vts.mark_turn_ready("CA2", "t2", audio_filename="abc.mp3")
    ready = vts.get_voice_turn("CA2", "t2")
    assert ready["status"] == "ready"
    assert ready["audio_filename"] == "abc.mp3"

    vts.mark_turn_consumed("CA2", "t2")
    consumed = vts.get_voice_turn("CA2", "t2")
    assert consumed["status"] == "consumed"


def test_increment_poll_count(fake_redis) -> None:
    vts.create_pending_turn(
        call_sid="CA3",
        turn_id="t3",
        recording_url="https://rec",
        from_number="+5511",
    )
    assert vts.increment_turn_poll_count("CA3", "t3") == 1
    assert vts.increment_turn_poll_count("CA3", "t3") == 2
    data = vts.get_voice_turn("CA3", "t3")
    assert data["poll_count"] == 2
