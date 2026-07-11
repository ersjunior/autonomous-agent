"""Unit tests — Fase F1 voice stream barge-in (detection, clear, abort)."""

from __future__ import annotations

import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.channels.voice.audio_pipeline import (
    UtteranceClosed,
    create_voice_stream_session,
    resample_8k_to_16k,
)
from agents.channels.voice.mulaw_codec import MULAW_FRAME_BYTES, chunk_mulaw, pcm16_to_mulaw
from agents.channels.voice.stream_session import (
    StreamCallControl,
    StreamUtteranceWorker,
    _handle_barge_in,
    _process_utterance_turn,
    _send_clear,
    _send_mulaw_frames,
)

pytestmark = pytest.mark.unit

MULAW_SILENCE_FRAME = bytes([0xFF] * MULAW_FRAME_BYTES)
MULAW_SPEECH_FRAME = pcm16_to_mulaw(struct.pack("<160h", *([8000] * 160)))


class MockVad:
    def __init__(self, pattern: list[bool]) -> None:
        self._pattern = list(pattern)
        self._index = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if self._index >= len(self._pattern):
            return False
        value = self._pattern[self._index]
        self._index += 1
        return value


def _session_with_agent_speaking(*, agent_speaking: bool, barge_in_ms: int = 300) -> tuple:
    control = StreamCallControl()
    if agent_speaking:
        control.begin_agent_playback()
    session = create_voice_stream_session(
        call_sid="CAbarge",
        stream_sid="MZbarge",
        frame_ms=20,
        barge_in_ms=barge_in_ms,
        barge_in_enabled=True,
        vad=MockVad([True] * 50),
    )
    session.listening = True
    session.agent_speaking_check = lambda: control.agent_speaking
    return session, control


def test_barge_in_triggers_after_sustained_speech() -> None:
    session, control = _session_with_agent_speaking(agent_speaking=True, barge_in_ms=300)
    triggered = False
    for _ in range(15):
        result = session.feed_mulaw_frame(MULAW_SPEECH_FRAME)
        if result.barge_in:
            triggered = True
            break
    assert triggered
    assert session.in_speech is True
    assert len(session.pcm_buffer) > 0


def test_short_speech_does_not_trigger_barge_in() -> None:
    session, _control = _session_with_agent_speaking(agent_speaking=True, barge_in_ms=300)
    vad = MockVad([True] * 5 + [False] * 5)
    session.vad = vad

    for _ in range(10):
        result = session.feed_mulaw_frame(MULAW_SPEECH_FRAME)
        assert not result.barge_in

    assert session.in_speech is False
    assert session.utterance_count == 0


def test_silence_during_playback_no_barge_in() -> None:
    session, _control = _session_with_agent_speaking(agent_speaking=True)
    session.vad = MockVad([False] * 20)

    for _ in range(20):
        result = session.feed_mulaw_frame(MULAW_SILENCE_FRAME)
        assert not result.barge_in

    assert session.barge_in_speech_frames == 0


def test_barge_in_disabled_ignores_inbound_during_agent_playback() -> None:
    """D1 parity: no utterance capture while agent is speaking (echo ignored)."""
    control = StreamCallControl()
    control.begin_agent_playback()
    session = create_voice_stream_session(
        call_sid="CAnobarge",
        stream_sid="MZnobarge",
        frame_ms=20,
        barge_in_enabled=False,
        silence_hangover_ms=600,
        min_utterance_ms=400,
        vad=MockVad([True] * 50),
    )
    session.listening = True
    session.agent_speaking_check = lambda: control.agent_speaking

    for _ in range(50):
        result = session.feed_mulaw_frame(MULAW_SPEECH_FRAME)
        assert result.utterance is None
        assert not result.barge_in

    assert session.utterance_count == 0


def test_barge_in_disabled_captures_after_playback_ends() -> None:
    """Gate reopens when agent_speaking clears (mark / end_agent_playback)."""
    control = StreamCallControl()
    control.begin_agent_playback()
    session = create_voice_stream_session(
        call_sid="CAnobarge2",
        stream_sid="MZnobarge2",
        frame_ms=20,
        barge_in_enabled=False,
        silence_hangover_ms=600,
        min_utterance_ms=400,
        vad=MockVad([True] * 30 + [False] * 35),
    )
    session.listening = True
    session.agent_speaking_check = lambda: control.agent_speaking

    for _ in range(10):
        assert session.feed_mulaw_frame(MULAW_SPEECH_FRAME).utterance is None

    control.end_agent_playback()

    utterance_closed = None
    for _ in range(70):
        result = session.feed_mulaw_frame(MULAW_SPEECH_FRAME)
        if result.utterance is not None:
            utterance_closed = result.utterance
            break

    assert utterance_closed is not None
    assert utterance_closed.index == 1


@pytest.mark.asyncio
async def test_send_clear_message_format() -> None:
    ws = AsyncMock()
    await _send_clear(ws, stream_sid="MZclear")
    payload = json.loads(ws.send_text.await_args.args[0])
    assert payload == {"event": "clear", "streamSid": "MZclear"}


@pytest.mark.asyncio
async def test_send_mulaw_frames_aborts_on_interrupt() -> None:
    ws = AsyncMock()
    control = StreamCallControl()
    control.begin_agent_playback()
    frames = [MULAW_SILENCE_FRAME] * 100
    send_count = 0

    async def send_side_effect(text: str) -> None:
        nonlocal send_count
        send_count += 1
        if send_count >= 5:
            control.request_playback_interrupt()

    ws.send_text = AsyncMock(side_effect=send_side_effect)

    completed = await _send_mulaw_frames(
        ws,
        stream_sid="MZabort",
        frames=frames,
        label="agent",
        control=control,
        barge_in_enabled=True,
    )

    assert completed is False
    assert send_count == 5


@pytest.mark.asyncio
async def test_handle_barge_in_sends_clear_once() -> None:
    ws = AsyncMock()
    control = StreamCallControl()
    control.begin_agent_playback()
    session = create_voice_stream_session(
        call_sid="CAhi",
        stream_sid="MZhi",
        vad=MagicMock(),
    )

    await _handle_barge_in(
        ws,
        stream_sid="MZhi",
        control=control,
        session=session,
        call_sid="CAhi",
    )
    await _handle_barge_in(
        ws,
        stream_sid="MZhi",
        control=control,
        session=session,
        call_sid="CAhi",
    )

    clear_events = [
        json.loads(c.args[0])
        for c in ws.send_text.await_args_list
        if json.loads(c.args[0]).get("event") == "clear"
    ]
    assert len(clear_events) == 1
    assert control.agent_speaking is False


@pytest.mark.asyncio
async def test_process_utterance_turn_aborts_on_interrupt_during_send() -> None:
    pcm_16k = resample_8k_to_16k(struct.pack("<320h", *([500] * 320)))
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=40, index=1)
    ws = AsyncMock()
    control = StreamCallControl()
    tts_wav = b"RIFF" + b"\x00" * 200
    many_frames = chunk_mulaw(b"\xff" * (160 * 50))

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="interrompa"),
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(
            "agents.channels.voice.stream_session._run_voice_agent_for_stream",
            AsyncMock(return_value=("Resposta longa do agente.", False)),
        ),
        patch(
            "agents.channels.voice.stream_session._synthesize_stream_mulaw_frames",
            AsyncMock(return_value=many_frames),
        ),
        patch("agents.channels.voice.stream_session.settings") as mock_settings,
    ):
        mock_settings.voice_stream_barge_in_enabled = True

        async def interrupt_mid_send(*args, **kwargs):
            control.request_playback_interrupt()
            return False

        with patch(
            "agents.channels.voice.stream_session._send_mulaw_frames",
            side_effect=interrupt_mid_send,
        ):
            await _process_utterance_turn(
                result,
                call_sid="CAint",
                stream_sid="MZint",
                websocket=ws,
                control=control,
            )

    mark_sent = any(
        json.loads(c.args[0]).get("event") == "mark"
        for c in ws.send_text.await_args_list
    )
    assert not mark_sent
    assert control.agent_speaking is False


@pytest.mark.asyncio
async def test_process_utterance_turn_no_abort_when_barge_in_disabled() -> None:
    pcm_16k = resample_8k_to_16k(struct.pack("<320h", *([500] * 320)))
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=40, index=1)
    ws = AsyncMock()
    control = StreamCallControl()

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="oi"),
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(
            "agents.channels.voice.stream_session._run_voice_agent_for_stream",
            AsyncMock(return_value=("Resposta.", False)),
        ),
        patch(
            "agents.channels.voice.stream_session._synthesize_stream_mulaw_frames",
            AsyncMock(return_value=[MULAW_SILENCE_FRAME]),
        ),
        patch("agents.channels.voice.stream_session.settings") as mock_settings,
    ):
        mock_settings.voice_stream_barge_in_enabled = False
        control.request_playback_interrupt()

        await _process_utterance_turn(
            result,
            call_sid="CAnoabort",
            stream_sid="MZnoabort",
            websocket=ws,
            control=control,
        )

    mark_sent = any(
        json.loads(c.args[0]).get("mark", {}).get("name") == "agent_response_done"
        for c in ws.send_text.await_args_list
        if json.loads(c.args[0]).get("event") == "mark"
    )
    assert mark_sent


def _mock_async_session_local() -> tuple:
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm, mock_session


@pytest.mark.asyncio
async def test_barge_in_utterance_processed_after_interrupt() -> None:
    """After barge-in, lead speech captured as next utterance via worker."""
    ws = AsyncMock()
    control = StreamCallControl()
    pcm = resample_8k_to_16k(struct.pack("<320h", *([500] * 320)))
    processed: list[int] = []

    async def fake_process(item, *, call_sid, stream_sid, websocket, control):
        processed.append(item.index)

    worker = StreamUtteranceWorker(
        call_sid="CAflow",
        stream_sid="MZflow",
        websocket=ws,
        control=control,
    )

    with patch(
        "agents.channels.voice.stream_session._process_utterance_turn",
        new=fake_process,
    ):
        worker.start()
        control.begin_agent_playback()
        control.request_playback_interrupt()
        control.end_agent_playback()
        worker.enqueue(UtteranceClosed(pcm16_16k=pcm, duration_ms=400, index=1))
        await worker._queue.join()
        await worker.shutdown()

    assert processed == [1]


@pytest.mark.asyncio
async def test_send_mulaw_frames_sends_all_when_barge_disabled_even_if_interrupt_set() -> None:
    """D1 parity: interrupt must not abort send when barge-in is off (echo capture passes control)."""
    ws = AsyncMock()
    control = StreamCallControl()
    control.request_playback_interrupt()
    frames = [MULAW_SILENCE_FRAME] * 5

    completed = await _send_mulaw_frames(
        ws,
        stream_sid="MZd1",
        frames=frames,
        label="agent",
        control=control,
        barge_in_enabled=False,
    )

    assert completed is True
    assert ws.send_text.await_count == 5


@pytest.mark.asyncio
async def test_send_mulaw_frames_sends_all_when_barge_enabled_interrupt_clear() -> None:
    ws = AsyncMock()
    control = StreamCallControl()
    control.begin_agent_playback()
    frames = [MULAW_SILENCE_FRAME] * 4

    completed = await _send_mulaw_frames(
        ws,
        stream_sid="MZok",
        frames=frames,
        label="agent",
        control=control,
        barge_in_enabled=True,
    )

    assert completed is True
    assert ws.send_text.await_count == 4


@pytest.mark.asyncio
async def test_process_utterance_clears_interrupt_before_playback_when_barge_enabled() -> None:
    pcm_16k = resample_8k_to_16k(struct.pack("<320h", *([500] * 320)))
    result = UtteranceClosed(pcm16_16k=pcm_16k, duration_ms=40, index=1)
    ws = AsyncMock()
    control = StreamCallControl()
    control.request_playback_interrupt()
    frames = [MULAW_SILENCE_FRAME] * 3
    begin_calls: list[bool] = []

    original_begin = StreamCallControl.begin_agent_playback

    def spy_begin(self: StreamCallControl) -> None:
        begin_calls.append(self.playback_interrupt.is_set())
        original_begin(self)

    with (
        patch(
            "agents.channels.voice.stream_session.speech_to_text",
            AsyncMock(return_value="oi"),
        ),
        patch(
            "app.services.voice_call_state.get_call_customer_number",
            return_value="+5511999999999",
        ),
        patch("app.services.voice_call_state.reset_silence_stage"),
        patch(
            "agents.channels.voice.stream_session._run_voice_agent_for_stream",
            AsyncMock(return_value=("Resposta.", False)),
        ),
        patch(
            "agents.channels.voice.stream_session._synthesize_stream_mulaw_frames",
            AsyncMock(return_value=frames),
        ),
        patch("agents.channels.voice.stream_session.settings") as mock_settings,
        patch.object(StreamCallControl, "begin_agent_playback", spy_begin),
    ):
        mock_settings.voice_stream_barge_in_enabled = True
        mock_settings.voice_stream_echo_debug_capture = False

        await _process_utterance_turn(
            result,
            call_sid="CAclear",
            stream_sid="MZclear",
            websocket=ws,
            control=control,
        )

    assert begin_calls == [False]
    media_sent = sum(
        1
        for c in ws.send_text.await_args_list
        if json.loads(c.args[0]).get("event") == "media"
    )
    assert media_sent == 3
