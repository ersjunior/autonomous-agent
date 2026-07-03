"""Tests — Fase A/B/C/D1 voice stream transport (WebSocket + VAD + STT + agent + TTS)."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
import wave
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from pydantic import ValidationError

from agents.channels.voice.audio_pipeline import (
    UtteranceClosed,
    create_voice_stream_session,
    create_voice_stream_session_from_settings,
    pcm16_16k_to_wav,
    resample_8k_to_16k,
)
from agents.channels.voice.mulaw_codec import (
    INTRO_FRAMES,
    MULAW_FRAME_BYTES,
    chunk_mulaw,
    generate_intro_beep_mulaw,
    pcm16_to_mulaw,
    wav_bytes_to_pcm16_mono,
)
from agents.channels.voice.stream_session import AGENT_RESPONSE_MARK
from app.core.config import Settings, VOICE_MEDIA_STREAM_WS_PATH, settings

pytestmark = pytest.mark.api

INBOUND_WEBHOOK = "/api/v1/channels/webhooks/voice/inbound"
MEDIA_STREAM_WS = "/api/v1/channels/webhooks/voice/media-stream"
EXPECTED_WSS = f"wss://example.com{VOICE_MEDIA_STREAM_WS_PATH}"

MULAW_SILENCE_FRAME = bytes([0xFF] * MULAW_FRAME_BYTES)

RUN_VOICE_AGENT_TURN = "app.services.voice_turn_processor.run_voice_agent_turn"
ASYNC_SESSION_LOCAL = "app.core.database.AsyncSessionLocal"


def _mock_async_session_local() -> tuple[MagicMock, AsyncMock]:
    """Context manager mock for AsyncSessionLocal (same pattern as record worker)."""
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm, mock_session


def _make_wav_8k_mono_pcm16(num_samples: int = 800) -> bytes:
    pcm = struct.pack(f"<{num_samples}h", *([1000] * num_samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm)
    return buf.getvalue()


class _MockVadPattern:
    def __init__(self, pattern: list[bool]) -> None:
        self._pattern = list(pattern)
        self._i = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if self._i >= len(self._pattern):
            return False
        v = self._pattern[self._i]
        self._i += 1
        return v


def _session_factory_with_vad(*, call_sid, stream_sid, settings=None):
    pattern = [False] * 3 + [True] * 30 + [False] * 35
    return create_voice_stream_session(
        call_sid=call_sid,
        stream_sid=stream_sid,
        silence_hangover_ms=600,
        min_utterance_ms=400,
        frame_ms=20,
        vad=_MockVadPattern(pattern),
    )


def _session_factory_noop_vad(*, call_sid, stream_sid, settings=None):
    mock_vad = MagicMock()
    mock_vad.is_speech.return_value = False
    return create_voice_stream_session(
        call_sid=call_sid,
        stream_sid=stream_sid,
        vad=mock_vad,
    )


@pytest.fixture(autouse=True)
def _mock_stream_vad_factory(request):
    """WS tests avoid requiring webrtcvad unless testing utterance detection."""
    if request.node.name in (
        "test_media_stream_ws_detects_utterance_after_intro",
        "test_media_stream_ws_transcribes_utterance_after_intro",
        "test_media_stream_ws_agent_response_outbound",
        "test_media_stream_ws_closes_gracefully_when_vad_missing",
    ):
        yield
        return
    with patch(
        "agents.channels.voice.stream_session.create_voice_stream_session_from_settings",
        side_effect=_session_factory_noop_vad,
    ):
        yield


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
            "app.api.v1.channels.is_voice_stream_available",
            return_value=True,
        ),
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


async def test_inbound_stream_degrades_to_record_when_vad_unavailable(
    client, monkeypatch, caplog
) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(settings, "voice_inbound_mode", "stream")
    fake_mp3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.mp3"

    with (
        patch(
            "app.api.v1.channels.is_voice_stream_available",
            return_value=False,
        ),
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
                "CallSid": "CAstreamfallback",
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
    assert any(
        "degradando para record" in r.message.lower()
        for r in caplog.records
    )


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


async def test_media_stream_ws_detects_utterance_after_intro(
    test_app, monkeypatch, caplog
) -> None:
    import logging
    from starlette.testclient import TestClient

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(settings, "voice_stream_echo_debug", False)

    with (
        patch(
            "agents.channels.voice.stream_session.create_voice_stream_session_from_settings",
            side_effect=_session_factory_with_vad,
        ),
        patch(
            "app.services.voice_call_state.get_voice_call_state",
            return_value={"from_number": "+5511", "silence_stage": 0},
        ),
    ):
        with TestClient(test_app) as tc:
            with tc.websocket_connect(MEDIA_STREAM_WS) as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": "MZutt",
                            "start": {
                                "streamSid": "MZutt",
                                "callSid": "CAutt001",
                                "tracks": ["inbound"],
                            },
                        }
                    )
                )

                for _ in range(len(INTRO_FRAMES) + 3):
                    msg = json.loads(ws.receive_text())
                    if msg.get("event") == "mark":
                        break

                tone_frames = chunk_mulaw(generate_intro_beep_mulaw(duration_sec=0.5))
                frames_to_send = [MULAW_SILENCE_FRAME] * 3
                for f in tone_frames:
                    frames_to_send.append(f[:MULAW_FRAME_BYTES])
                frames_to_send.extend([MULAW_SILENCE_FRAME] * 40)

                for frame in frames_to_send:
                    ws.send_text(
                        json.dumps(
                            {
                                "event": "media",
                                "streamSid": "MZutt",
                                "media": {
                                    "payload": base64.b64encode(frame).decode("ascii"),
                                    "track": "inbound",
                                },
                            }
                        )
                    )

                ws.send_text(json.dumps({"event": "stop", "streamSid": "MZutt"}))

    assert any("utterance closed" in r.message for r in caplog.records)


@pytest.mark.unit
async def test_transcribe_utterance_calls_speech_to_text_with_wav() -> None:
    from agents.channels.voice.stream_session import _process_utterance_turn

    pcm_16k = resample_8k_to_16k(struct.pack("<160h", *([1000] * 160)))
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=20, index=1)
    stt_mock = AsyncMock(return_value="ola mundo")
    ws = AsyncMock()

    with (
        patch("agents.channels.voice.stream_session.speech_to_text", stt_mock),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="",
        ),
    ):
        await _process_utterance_turn(
            result,
            call_sid="CAstt",
            stream_sid="MZstt",
            websocket=ws,
            response_lock=asyncio.Lock(),
        )

    stt_mock.assert_awaited_once()
    wav_bytes = stt_mock.await_args.args[0]
    assert stt_mock.await_args.kwargs["language"] == "pt"
    assert stt_mock.await_args.kwargs["filename"] == "utterance.wav"
    assert stt_mock.await_args.kwargs["content_type"] == "audio/wav"
    assert wav_bytes[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.readframes(wf.getnframes()) == pcm_16k
    ws.send_text.assert_not_awaited()


@pytest.mark.unit
async def test_schedule_utterance_transcription_runs_stt_in_background() -> None:
    from agents.channels.voice.stream_session import _schedule_utterance_transcription

    result = UtteranceClosed(pcm16_16k=b"\x00\x00" * 320, duration_ms=20, index=2)
    stt_tasks: set[asyncio.Task[None]] = set()
    invoked: list[str] = []

    async def _fake_process(_result, *, call_sid, stream_sid, websocket, response_lock):
        invoked.append(call_sid or "")

    with patch(
        "agents.channels.voice.stream_session._process_utterance_turn",
        new=_fake_process,
    ):
        await _schedule_utterance_transcription(
            result,
            call_sid="CAbg",
            stream_sid="MZbg",
            websocket=AsyncMock(),
            response_lock=asyncio.Lock(),
            stt_tasks=stt_tasks,
        )
        await asyncio.sleep(0)

    assert invoked == ["CAbg"]
    assert not stt_tasks


async def test_media_stream_ws_transcribes_utterance_after_intro(
    test_app, monkeypatch, caplog
) -> None:
    import logging
    from starlette.testclient import TestClient

    from agents.channels.voice.stream_session import _process_utterance_turn

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(settings, "voice_stream_echo_debug", False)
    stt_mock = AsyncMock(return_value="ola mundo")

    async def _inline_schedule(
        result, *, call_sid, stream_sid, websocket, response_lock, stt_tasks
    ):
        await _process_utterance_turn(
            result,
            call_sid=call_sid,
            stream_sid=stream_sid,
            websocket=websocket,
            response_lock=response_lock,
        )

    with (
        patch(
            "agents.channels.voice.stream_session.create_voice_stream_session_from_settings",
            side_effect=_session_factory_with_vad,
        ),
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            stt_mock,
        ),
        patch(
            "agents.channels.voice.stream_session._schedule_utterance_transcription",
            side_effect=_inline_schedule,
        ),
        patch(
            "app.services.voice_call_state.get_voice_call_state",
            return_value={"from_number": "+5511", "silence_stage": 0},
        ),
    ):
        with TestClient(test_app) as tc:
            with tc.websocket_connect(MEDIA_STREAM_WS) as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": "MZstt",
                            "start": {
                                "streamSid": "MZstt",
                                "callSid": "CAstt001",
                                "tracks": ["inbound"],
                            },
                        }
                    )
                )

                for _ in range(len(INTRO_FRAMES) + 3):
                    msg = json.loads(ws.receive_text())
                    if msg.get("event") == "mark":
                        break

                tone_frames = chunk_mulaw(generate_intro_beep_mulaw(duration_sec=0.5))
                frames_to_send = [MULAW_SILENCE_FRAME] * 3
                for f in tone_frames:
                    frames_to_send.append(f[:MULAW_FRAME_BYTES])
                frames_to_send.extend([MULAW_SILENCE_FRAME] * 40)

                for frame in frames_to_send:
                    ws.send_text(
                        json.dumps(
                            {
                                "event": "media",
                                "streamSid": "MZstt",
                                "media": {
                                    "payload": base64.b64encode(frame).decode("ascii"),
                                    "track": "inbound",
                                },
                            }
                        )
                    )

                ws.send_text(json.dumps({"event": "stop", "streamSid": "MZstt"}))

    stt_mock.assert_awaited_once()
    wav_bytes = stt_mock.await_args.args[0]
    assert stt_mock.await_args.kwargs["content_type"] == "audio/wav"
    assert wav_bytes[:4] == b"RIFF"
    assert any(
        "Voice stream STT utterance" in r.message and "ola mundo" in r.message
        for r in caplog.records
    )
    assert any("stt_ms=" in r.message for r in caplog.records)


async def test_media_stream_ws_closes_gracefully_when_vad_missing(
    test_app, caplog
) -> None:
    import logging
    from starlette.testclient import TestClient

    caplog.set_level(logging.ERROR)

    def _raise_vad_missing(*, call_sid, stream_sid, settings=None):
        raise ModuleNotFoundError("No module named 'webrtcvad'")

    with patch(
        "agents.channels.voice.stream_session.create_voice_stream_session_from_settings",
        side_effect=_raise_vad_missing,
    ):
        with TestClient(test_app) as tc:
            with tc.websocket_connect(MEDIA_STREAM_WS) as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": "MZnovad",
                            "start": {
                                "streamSid": "MZnovad",
                                "callSid": "CAnovad",
                            },
                        }
                    )
                )
                # Handler breaks after start failure — no intro beep expected.

    assert any(
        "webrtcvad ausente" in r.message.lower()
        for r in caplog.records
    )


@pytest.mark.unit
def test_wav_bytes_to_pcm16_mono_8k() -> None:
    wav = _make_wav_8k_mono_pcm16(160)
    pcm = wav_bytes_to_pcm16_mono(wav, expected_rate=8000)
    assert len(pcm) == 160 * 2


@pytest.mark.unit
async def test_response_lock_serializes_pipeline() -> None:
    lock = asyncio.Lock()
    order: list[str] = []

    async def first() -> None:
        async with lock:
            order.append("start1")
            await asyncio.sleep(0.05)
            order.append("end1")

    async def second() -> None:
        async with lock:
            order.append("start2")
            order.append("end2")

    t1 = asyncio.create_task(first())
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(second())
    await asyncio.gather(t1, t2)
    assert order == ["start1", "end1", "start2", "end2"]


@pytest.mark.unit
async def test_run_voice_agent_for_stream_matches_record_call_signature() -> None:
    """Stream must call run_voice_agent_turn like process_voice_inbound_turn (session positional)."""
    from agents.channels.voice.stream_session import _run_voice_agent_for_stream

    mock_cm, mock_session = _mock_async_session_local()

    with (
        patch(ASYNC_SESSION_LOCAL, return_value=mock_cm),
        patch(RUN_VOICE_AGENT_TURN, autospec=True) as agent_mock,
    ):
        agent_mock.return_value = "  resposta  "
        out = await _run_voice_agent_for_stream(
            from_number="+5511999999999",
            transcript="olá",
            call_sid="CAtest",
        )

    agent_mock.assert_awaited_once_with(
        mock_session,
        from_number="+5511999999999",
        transcript="olá",
        call_sid="CAtest",
    )
    assert out == "  resposta  "


@pytest.mark.unit
def test_run_voice_agent_turn_signature_has_session_not_db() -> None:
    """Regression guard: first param is session, not db= kwarg."""
    import inspect

    from app.services.voice_turn_processor import run_voice_agent_turn

    params = inspect.signature(run_voice_agent_turn).parameters
    assert "session" in params
    assert params["session"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert "db" not in params

    mock = create_autospec(run_voice_agent_turn, spec_set=True)
    with pytest.raises(TypeError, match="db"):
        mock(AsyncMock(), from_number="+5511", transcript="hi", db=AsyncMock())


@pytest.mark.unit
async def test_process_utterance_turn_agent_tts_sends_mulaw_and_mark() -> None:
    from agents.channels.voice.stream_session import (
        STREAM_TTS_SAMPLE_RATE,
        _process_utterance_turn,
    )

    pcm_16k = resample_8k_to_16k(struct.pack("<320h", *([500] * 320)))
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=40, index=3)
    ws = AsyncMock()
    tts_wav = _make_wav_8k_mono_pcm16(800)
    mock_cm, mock_session = _mock_async_session_local()

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="quero agendar"),
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(ASYNC_SESSION_LOCAL, return_value=mock_cm),
        patch(RUN_VOICE_AGENT_TURN, autospec=True) as agent_mock,
        patch(
            "agents.channels.voice.stream_session.text_to_speech",
            autospec=True,
        ) as tts_mock,
    ):
        agent_mock.return_value = "Claro, para quando?"
        tts_mock.return_value = tts_wav
        await _process_utterance_turn(
            result,
            call_sid="CAd1",
            stream_sid="MZd1",
            websocket=ws,
            response_lock=asyncio.Lock(),
        )

    agent_mock.assert_awaited_once_with(
        mock_session,
        from_number="+5511999999999",
        transcript="quero agendar",
        call_sid="CAd1",
    )

    tts_mock.assert_awaited_once_with(
        "Claro, para quando?",
        sample_rate=STREAM_TTS_SAMPLE_RATE,
    )

    sent = [json.loads(c.args[0]) for c in ws.send_text.await_args_list]
    media_events = [p for p in sent if p.get("event") == "media"]
    mark_events = [p for p in sent if p.get("event") == "mark"]
    assert len(media_events) >= 1
    assert media_events[0]["streamSid"] == "MZd1"
    assert mark_events[-1]["mark"]["name"] == AGENT_RESPONSE_MARK


@pytest.mark.unit
async def test_process_utterance_turn_serializes_two_utterances() -> None:
    from agents.channels.voice.stream_session import _process_utterance_turn
    from app.services.voice_turn_processor import run_voice_agent_turn

    lock = asyncio.Lock()
    ws = AsyncMock()
    order: list[int] = []
    tts_wav = _make_wav_8k_mono_pcm16(160)
    mock_cm, mock_session = _mock_async_session_local()

    async def agent_side_effect(
        session,
        *,
        from_number,
        transcript,
        call_sid=None,
        agent_timings=None,
        voice_turn_out=None,
    ):
        order.append(int(transcript.split("#")[1]))
        await asyncio.sleep(0.03)
        return f"resp-{transcript}"

    pcm = resample_8k_to_16k(struct.pack("<320h", *([100] * 320)))
    stt_call = 0

    async def stt_side_effect(*args, **kwargs):
        nonlocal stt_call
        stt_call += 1
        n = stt_call
        await asyncio.sleep(0.001 * n)
        return f"utt#{n}"

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            side_effect=stt_side_effect,
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(ASYNC_SESSION_LOCAL, return_value=mock_cm),
        patch(
            RUN_VOICE_AGENT_TURN,
            new=AsyncMock(spec=run_voice_agent_turn, side_effect=agent_side_effect),
        ),
        patch(
            "agents.channels.voice.stream_session.text_to_speech",
            autospec=True,
        ) as tts_mock,
    ):
        tts_mock.return_value = tts_wav
        r1 = UtteranceClosed(pcm16_16k=pcm, duration_ms=40, index=1)
        r2 = UtteranceClosed(pcm16_16k=pcm, duration_ms=40, index=2)
        t1 = asyncio.create_task(
            _process_utterance_turn(
                r1,
                call_sid="CAser",
                stream_sid="MZser",
                websocket=ws,
                response_lock=lock,
            )
        )
        t2 = asyncio.create_task(
            _process_utterance_turn(
                r2,
                call_sid="CAser",
                stream_sid="MZser",
                websocket=ws,
                response_lock=lock,
            )
        )
        await asyncio.gather(t1, t2)

    assert order == [1, 2]


async def test_media_stream_ws_agent_response_outbound(
    test_app, monkeypatch, caplog
) -> None:
    import logging
    from starlette.testclient import TestClient

    from agents.channels.voice.stream_session import _process_utterance_turn

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(settings, "voice_stream_echo_debug", False)
    tts_wav = _make_wav_8k_mono_pcm16(800)
    mock_cm, mock_session = _mock_async_session_local()

    async def _inline_schedule(
        result, *, call_sid, stream_sid, websocket, response_lock, stt_tasks
    ):
        await _process_utterance_turn(
            result,
            call_sid=call_sid,
            stream_sid=stream_sid,
            websocket=websocket,
            response_lock=response_lock,
        )

    with (
        patch(
            "agents.channels.voice.stream_session.create_voice_stream_session_from_settings",
            side_effect=_session_factory_with_vad,
        ),
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="quero agendar"),
        ),
        patch(
            "agents.channels.voice.stream_session._schedule_utterance_transcription",
            side_effect=_inline_schedule,
        ),
        patch(
            "app.services.voice_call_state.get_voice_call_state",
            return_value={"from_number": "+5511", "silence_stage": 0},
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(ASYNC_SESSION_LOCAL, return_value=mock_cm),
        patch(RUN_VOICE_AGENT_TURN, autospec=True) as agent_mock,
        patch(
            "agents.channels.voice.stream_session.text_to_speech",
            autospec=True,
        ) as tts_mock,
    ):
        agent_mock.return_value = "Claro, para quando?"
        tts_mock.return_value = tts_wav
        with TestClient(test_app) as tc:
            with tc.websocket_connect(MEDIA_STREAM_WS) as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": "MZd1ws",
                            "start": {
                                "streamSid": "MZd1ws",
                                "callSid": "CAd1ws",
                                "tracks": ["inbound"],
                            },
                        }
                    )
                )

                for _ in range(len(INTRO_FRAMES) + 3):
                    msg = json.loads(ws.receive_text())
                    if msg.get("event") == "mark":
                        break

                tone_frames = chunk_mulaw(generate_intro_beep_mulaw(duration_sec=0.5))
                frames_to_send = [MULAW_SILENCE_FRAME] * 3
                for f in tone_frames:
                    frames_to_send.append(f[:MULAW_FRAME_BYTES])
                frames_to_send.extend([MULAW_SILENCE_FRAME] * 40)

                for frame in frames_to_send:
                    ws.send_text(
                        json.dumps(
                            {
                                "event": "media",
                                "streamSid": "MZd1ws",
                                "media": {
                                    "payload": base64.b64encode(frame).decode("ascii"),
                                    "track": "inbound",
                                },
                            }
                        )
                    )

                ws.send_text(json.dumps({"event": "stop", "streamSid": "MZd1ws"}))

    assert any(
        "Voice stream agent response" in r.message and "Claro, para quando?" in r.message
        for r in caplog.records
    )
