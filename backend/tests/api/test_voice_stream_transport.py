"""Tests — Fase A voice stream transport (WebSocket + inbound TwiML branch)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from agents.channels.voice.mulaw_codec import (
    INTRO_FRAMES,
    MULAW_FRAME_BYTES,
    chunk_mulaw,
    pcm16_to_mulaw,
)
from app.core.config import Settings, VOICE_MEDIA_STREAM_WS_PATH, settings

pytestmark = pytest.mark.api

INBOUND_WEBHOOK = "/api/v1/channels/webhooks/voice/inbound"
MEDIA_STREAM_WS = "/api/v1/channels/webhooks/voice/media-stream"
EXPECTED_WSS = f"wss://example.com{VOICE_MEDIA_STREAM_WS_PATH}"


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(settings, "voice_inbound_mode", "record")
    monkeypatch.setattr(settings, "voice_stream_echo_debug", False)


async def test_inbound_stream_mode_returns_connect_stream_twiml(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_inbound_mode", "stream")
    remember_mock = MagicMock()
    status_mock = MagicMock()

    with (
        patch(
            "app.services.settings_sync.ensure_settings_fresh_async",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.voice_call_state.remember_call_from_number",
            remember_mock,
        ),
        patch(
            "app.api.v1.channels._register_voice_call_status_callback",
            status_mock,
        ),
    ):
        response = await client.post(
            INBOUND_WEBHOOK,
            data={
                "CallSid": "CAstream001",
                "From": "+5511999999999",
                "To": "+5511888888888",
            },
        )

    assert response.status_code == 200
    assert "application/xml" in response.headers.get("content-type", "")
    body = response.text
    assert "<Connect>" in body
    assert "<Stream" in body
    assert EXPECTED_WSS in body
    assert "<Record" not in body
    remember_mock.assert_called_once_with("CAstream001", "+5511999999999")
    status_mock.assert_called_once_with("CAstream001")


async def test_inbound_record_mode_unchanged(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "voice_inbound_mode", "record")
    fake_mp3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"

    with (
        patch(
            "app.services.settings_sync.ensure_settings_fresh_async",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.v1.channels.ensure_greeting_audio_filename",
            return_value=fake_mp3,
        ),
    ):
        response = await client.post(
            INBOUND_WEBHOOK,
            data={
                "CallSid": "CArecord001",
                "From": "+5511999999999",
                "To": "+5511888888888",
            },
        )

    assert response.status_code == 200
    body = response.text
    assert "<Play>" in body
    assert "<Record" in body
    assert "<Connect>" not in body
    assert fake_mp3 in body


def test_voice_inbound_mode_invalid_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"voice_inbound_mode": "foo"})


def test_voice_media_stream_wss_url_from_https() -> None:
    cfg = Settings.model_construct(public_base_url="https://tunnel.example.com")
    assert cfg.voice_media_stream_wss_url() == (
        f"wss://tunnel.example.com{VOICE_MEDIA_STREAM_WS_PATH}"
    )


@pytest.mark.unit
def test_pcm16_to_mulaw_output_size() -> None:
    pcm = b"\x00\x00" * 160
    mulaw = pcm16_to_mulaw(pcm)
    assert len(mulaw) == 160


@pytest.mark.unit
def test_intro_frames_are_160_bytes() -> None:
    assert len(INTRO_FRAMES) > 0
    for frame in INTRO_FRAMES:
        assert len(frame) <= MULAW_FRAME_BYTES
        assert len(frame) > 0


@pytest.mark.unit
def test_chunk_mulaw_splits_correctly() -> None:
    data = bytes(range(256)) * 2  # 512 bytes
    frames = chunk_mulaw(data, frame_size=160)
    assert len(frames) == 4
    assert sum(len(f) for f in frames) == 512


async def test_media_stream_ws_protocol_beep_and_mark(test_app, monkeypatch) -> None:
    from starlette.testclient import TestClient

    monkeypatch.setattr(settings, "voice_stream_echo_debug", False)
    known_state = {"from_number": "+5511999999999", "silence_stage": 0}

    with patch(
        "app.services.voice_call_state.get_voice_call_state",
        return_value=known_state,
    ):
        with TestClient(test_app) as tc:
            with tc.websocket_connect(MEDIA_STREAM_WS) as ws:
                ws.send_text(
                    json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
                )
                ws.send_text(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": "MZteststream",
                            "start": {
                                "streamSid": "MZteststream",
                                "callSid": "CAtestws001",
                                "tracks": ["inbound"],
                            },
                        }
                    )
                )

                got_mark = False
                media_out = 0
                for _ in range(len(INTRO_FRAMES) + 5):
                    raw = ws.receive_text()
                    msg = json.loads(raw)
                    if msg.get("event") == "media":
                        media_out += 1
                        assert msg.get("streamSid") == "MZteststream"
                        assert msg.get("media", {}).get("payload")
                    if msg.get("event") == "mark":
                        got_mark = True
                        assert msg.get("mark", {}).get("name") == "intro_done"
                        break

                assert got_mark
                assert media_out == len(INTRO_FRAMES)

                ws.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": "MZteststream",
                            "media": {"payload": "AA==", "track": "inbound"},
                        }
                    )
                )
                ws.send_text(
                    json.dumps({"event": "stop", "streamSid": "MZteststream"})
                )


async def test_media_stream_ws_echo_when_debug_enabled(test_app, monkeypatch) -> None:
    from starlette.testclient import TestClient

    monkeypatch.setattr(settings, "voice_stream_echo_debug", True)

    with patch(
        "app.services.voice_call_state.get_voice_call_state",
        return_value={"from_number": "+5511", "silence_stage": 0},
    ):
        with TestClient(test_app) as tc:
            with tc.websocket_connect(MEDIA_STREAM_WS) as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": "MZecho",
                            "start": {"streamSid": "MZecho", "callSid": "CAecho"},
                        }
                    )
                )

                for _ in range(len(INTRO_FRAMES) + 2):
                    msg = json.loads(ws.receive_text())
                    if msg.get("event") == "mark":
                        break

                payload = "dGVzdA=="
                ws.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": "MZecho",
                            "media": {"payload": payload, "track": "inbound"},
                        }
                    )
                )
                echoed = json.loads(ws.receive_text())
                assert echoed["event"] == "media"
                assert echoed["media"]["payload"] == payload

                ws.send_text(json.dumps({"event": "stop", "streamSid": "MZecho"}))
